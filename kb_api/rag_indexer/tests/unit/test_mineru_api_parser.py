import json
from types import SimpleNamespace

import httpx
import pytest

from kb_api.rag_indexer.parser.common.config import RetryConfig
from kb_api.rag_indexer.parser.common.schema import TextBlock
from kb_api.rag_indexer.parser.common.upstream import UpstreamServiceError

pytestmark = pytest.mark.unit


@pytest.fixture
def config():
    return SimpleNamespace(
        enable=True, base_url="http://mineru:8000/", timeout=10,
        tier="basic", parse_method="auto", retry=RetryConfig(3, 0),
    )


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "download.pdf"
    path.write_bytes(b"%PDF-probe")
    return path


@pytest.fixture
def structured_content():
    return {
        "metadata": {
            "file_suffix": "pdf", "producer": {"name": "mineru", "version": "4.0.6"},
            "document": {"page_count": 1, "page_count_kind": "physical"},
        },
        "pages": [{"page_idx": 0, "blocks": [
            {"type": "paragraph_title", "index": 0, "bbox": [0.1, 0.1, 0.8, 0.2],
             "level": 2, "content": "Heading"},
            {"type": "text", "index": 1, "bbox": [0.1, 0.3, 0.8, 0.4],
             "content": "Paragraph"},
        ]}],
        "is_full_document": True,
    }


def workflow(structured_content, calls, *, statuses=None):
    statuses = iter(statuses or ["running", "completed"])

    def handle(request):
        calls.append(request)
        assert "authorization" not in request.headers
        path = request.url.path
        if path == "/v1/uploads":
            assert json.loads(request.content) == {
                "filename": "report.pdf", "bytes": 10, "mime_type": "application/pdf", "purpose": "parse",
            }
            return httpx.Response(200, json={
                "id": "upload-1", "upload_url": "http://upload:8000/content",
                "upload_method": "PUT", "upload_headers": {"Content-Type": "application/pdf", "X-Upload": "yes"},
            })
        if path == "/content":
            assert request.method == "PUT"
            assert request.content == b"%PDF-probe"
            assert request.headers["x-upload"] == "yes"
            return httpx.Response(200, json={})
        if path == "/v1/uploads/upload-1/complete":
            assert json.loads(request.content) == {}
            return httpx.Response(200, json={"file": {"id": "file-1"}})
        if path == "/v1/parse/jobs":
            assert json.loads(request.content) == {
                "files": [{"source": {"type": "file_id", "file_id": "file-1"}}],
                "tier": "basic", "ocr_mode": "auto", "output_formats": ["structured_content"],
            }
            return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        if path == "/v1/parse/jobs/job-1":
            status = next(statuses)
            return httpx.Response(200, json={"job_id": "job-1", "status": status, "files": [{
                "status": "completed" if status == "completed" else status,
                "output_files": {"structured_content": {"file_id": "output-1", "bytes": 100}},
                "error": {"message": "engine failed"},
            }]})
        if path == "/v1/files/output-1/content":
            return httpx.Response(302, headers={"Location": "http://cdn:8000/result.json"})
        assert path == "/result.json"
        return httpx.Response(200, content=json.dumps(structured_content).encode(), headers={"Content-Type": "application/octet-stream"})

    return handle


def parser_for(config, handle):
    from kb_api.rag_indexer.parser.providers.mineru.api_parser import MineruApiDocumentParser

    return MineruApiDocumentParser(config, http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def test_upload_job_download_and_direct_conversion(config, document, structured_content, monkeypatch):
    calls = []
    parser = parser_for(config, workflow(structured_content, calls))
    monkeypatch.setenv("MINERU_API_KEY", "must-not-be-read")
    monkeypatch.setattr("kb_api.rag_indexer.parser.providers.mineru.api_parser.time.sleep", lambda _: None)
    assert not parser.ready
    parser.start()
    parser.start()
    assert parser.ready
    assert parser.parse_file(str(document), original_filename="report.pdf") == [
        TextBlock("Heading", page=1, kind="heading", level=2),
        TextBlock("Paragraph", page=1, kind="text"),
    ]
    assert [request.method for request in calls] == ["POST", "PUT", "POST", "POST", "GET", "GET", "GET", "GET"]
    assert all(0 < request.extensions["timeout"]["read"] <= config.timeout for request in calls)
    parser.stop()
    parser.stop()
    assert not parser.ready


@pytest.mark.parametrize("stage", ["/v1/uploads", "/v1/uploads/upload-1/complete", "/v1/parse/jobs"])
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_post_transport_error_never_replays_create(config, document, structured_content, stage, error_type):
    calls = []
    handle = workflow(structured_content, calls)
    attempts = []

    def fail(request):
        if request.url.path == stage:
            attempts.append(request)
            raise error_type("ambiguous POST", request=request)
        return handle(request)

    parser = parser_for(config, fail)
    with pytest.raises(UpstreamServiceError) as raised:
        parser.parse_file(str(document), original_filename="report.pdf")
    assert raised.value.status_code == (504 if error_type is httpx.ReadTimeout else 503)
    assert len(attempts) == 1
    parser.stop()


@pytest.mark.parametrize("status", [400, 403, 422])
def test_post_rejection_preserves_error_without_retry(config, document, status):
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "invalid upload"}})

    parser = parser_for(config, reject)
    with pytest.raises(UpstreamServiceError) as raised:
        parser.parse_file(str(document))
    assert raised.value.error == "invalid upload"
    assert raised.value.retryable is False
    assert len(calls) == 1
    parser.stop()


@pytest.mark.parametrize("stage,error", [
    ("/content", "timeout"), ("/v1/parse/jobs/job-1", "503"), ("/v1/uploads", "503"),
])
def test_retry_is_per_request_not_whole_workflow(config, document, structured_content, monkeypatch, stage, error):
    calls = []
    handle = workflow(structured_content, calls, statuses=["completed"])
    attempts = []

    def transient(request):
        if request.url.path == stage:
            attempts.append(request)
            if len(attempts) == 1:
                if error == "timeout":
                    raise httpx.ReadTimeout("temporary", request=request)
                return httpx.Response(503, json={"error": {"message": "temporary"}})
        return handle(request)

    parser = parser_for(config, transient)
    monkeypatch.setattr("kb_api.rag_indexer.parser.providers.mineru.api_parser.time.sleep", lambda _: None)
    assert parser.parse_file(str(document), original_filename="report.pdf")
    assert len(attempts) == 2
    assert sum(request.url.path == "/v1/parse/jobs" for request in calls) == 1
    parser.stop()


@pytest.mark.parametrize("status", ["failed", "partial", "canceled", "unexpected"])
def test_terminal_or_unknown_job_fails_without_download(config, document, structured_content, status):
    calls = []
    parser = parser_for(config, workflow(structured_content, calls, statuses=[status]))
    with pytest.raises(UpstreamServiceError) as raised:
        parser.parse_file(str(document), original_filename="report.pdf")
    assert raised.value.service == "parser"
    assert raised.value.retryable is False
    assert not any("/v1/files/" in request.url.path for request in calls)
    if status in {"failed", "partial"}:
        assert "engine failed" in str(raised.value)
    parser.stop()


@pytest.mark.parametrize("phase", ["poll", "retry"])
def test_total_deadline_bounds_requests_and_sleep(config, document, structured_content, monkeypatch, phase):
    calls = []
    clock = [0.0]
    sleeps = []
    config.timeout = 1
    config.retry = RetryConfig(3, 100)
    handle = workflow(structured_content, calls, statuses=["running"])

    def respond(request):
        if phase == "retry" and request.url.path == "/content":
            calls.append(request)
            return httpx.Response(503)
        return handle(request)

    parser = parser_for(config, respond)
    monkeypatch.setattr("kb_api.rag_indexer.parser.providers.mineru.api_parser.time.monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("kb_api.rag_indexer.parser.providers.mineru.api_parser.time.sleep", sleep)
    with pytest.raises(UpstreamServiceError) as raised:
        parser.parse_file(str(document), original_filename="report.pdf")
    assert raised.value.status_code == 504
    assert clock[0] <= config.timeout
    assert sleeps and all(0 < seconds <= config.timeout for seconds in sleeps)
    if phase == "retry":
        assert sum(request.url.path == "/content" for request in calls) == 1
    parser.stop()


@pytest.mark.parametrize("result", ["invalid", "empty", "missing_output"])
def test_rejects_invalid_or_empty_result(config, document, structured_content, result):
    calls = []
    if result == "empty":
        structured_content["pages"][0]["blocks"] = []
    handle = workflow(structured_content, calls, statuses=["completed"])

    def respond(request):
        if result == "invalid" and request.url.path == "/result.json":
            return httpx.Response(200, content=b"not json")
        if result == "missing_output" and request.url.path == "/v1/parse/jobs/job-1":
            return httpx.Response(200, json={"status": "completed", "files": [{"status": "completed", "output_files": {}}]})
        return handle(request)

    parser = parser_for(config, respond)
    with pytest.raises((UpstreamServiceError, ValueError)):
        parser.parse_file(str(document), original_filename="report.pdf")
    parser.stop()
