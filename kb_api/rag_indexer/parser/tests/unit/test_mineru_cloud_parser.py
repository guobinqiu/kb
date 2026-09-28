import io
import json
import zipfile

import httpx
import pytest


def test_cloud_parses_single_url_without_uploading_file():
    from kb_api.rag_indexer.parser.providers.mineru.cloud_parser import MineruCloudDocumentParser
    from kb_api.rag_indexer.parser.common.config import MineruCloudParserConfig

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("document_content_list.json", json.dumps([
            {"type": "text", "text": "Extracted paragraph", "page_idx": 0},
        ]))
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path == "/api/v4/extract/task"
            assert request.headers["authorization"] == "Bearer test-token"
            assert json.loads(request.content) == {
                "url": "https://storage.example/report.doc?signature=abc",
                "model_version": "vlm", "enable_formula": True,
                "enable_table": True, "language": "ch",
            }
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task-1"}})
        if request.url.path == "/api/v4/extract/task/task-1":
            return httpx.Response(200, json={"code": 0, "data": {
                "state": "done", "full_zip_url": "https://cdn.example/result.zip",
            }})
        assert request.url.host == "cdn.example"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=archive.getvalue())

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        parser = MineruCloudDocumentParser(MineruCloudParserConfig(api_key="test-token"), http_client=client)
        blocks = parser.parse_url("https://storage.example/report.doc?signature=abc")
    assert blocks[0].text == "Extracted paragraph"
    assert calls == [("POST", "/api/v4/extract/task"), ("GET", "/api/v4/extract/task/task-1"), ("GET", "/result.zip")]


@pytest.mark.parametrize("response", [
    {"code": -10001, "msg": "invalid token"},
    {"code": 0, "data": {"state": "failed", "err_msg": "unsupported file"}},
])
def test_cloud_preserves_provider_error(response):
    from kb_api.rag_indexer.parser.providers.mineru.cloud_parser import MineruCloudDocumentParser
    from kb_api.rag_indexer.parser.common.config import MineruCloudParserConfig
    from kb_api.rag_indexer.parser.common.upstream import UpstreamServiceError

    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task-1"}})
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        parser = MineruCloudDocumentParser(MineruCloudParserConfig(api_key="test-token"), http_client=client)
        with pytest.raises(UpstreamServiceError) as caught:
            parser.parse_url("https://storage.example/report.pdf")
    assert caught.value.error == response.get("msg", response.get("data", {}).get("err_msg"))
    assert caught.value.retryable is False
