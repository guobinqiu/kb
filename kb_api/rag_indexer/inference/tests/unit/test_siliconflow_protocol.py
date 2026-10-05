import json

import httpx
import pytest

from kb_api.rag_indexer.common.config import RetryConfig
from kb_api.rag_indexer.common.upstream import UpstreamServiceError, upstream_error
from kb_api.rag_indexer.common import upstream as task_ids
from kb_api.rag_indexer.inference.service import InferenceComponents
from kb_api.rag_indexer.inference.providers.siliconflow import SiliconFlowDenseClient


@pytest.fixture
def task_context():
    request_id = "a" * 32
    token = task_ids._task_trace_id.set(request_id)
    try:
        yield request_id
    finally:
        task_ids._task_trace_id.reset(token)


@pytest.fixture
def make_client():

    clients = []

    def make(handler, **kwargs):
        client = InferenceComponents(SiliconFlowDenseClient(
            base_url="https://api.siliconflow.cn/v1",
            api_key="test-external-key",
            model="BAAI/bge-m3",
            timeout=12.0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            retry=kwargs.pop("retry", RetryConfig(max_attempts=1)),
            **kwargs,
        ))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_dense_batch_order_and_query(make_client):
    def handler(request):
        assert str(request.url) == "https://api.siliconflow.cn/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-external-key"
        assert request.extensions["timeout"]["read"] == 12.0
        payload = json.loads(request.content)
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["encoding_format"] == "float"
        assert "dimensions" not in payload
        if payload["input"] == ["a", "b"]:
            return httpx.Response(200, json={"data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]})
        assert payload["input"] == "q"
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.6]}]})

    client = make_client(handler)
    assert client.dense.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert client.dense.embed_query("q") == [0.5, 0.6]


def test_dimensions_are_sent_for_documents_and_queries(make_client):
    inputs = []

    def handler(request):
        payload = json.loads(request.content)
        assert payload["dimensions"] == 768
        inputs.append(payload["input"])
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 768}]})

    client = make_client(handler, dimensions=768)
    assert len(client.dense.embed_documents(["document"])[0]) == 768
    assert len(client.dense.embed_query("query")) == 768
    assert inputs == [["document"], "query"]


def test_dense_http_error_logs_model_status_without_response_body(make_client, caplog):
    def handler(request):
        return httpx.Response(
            402,
            request=request,
            json={"code": 30001, "message": "balance is insufficient"},
        )

    client = make_client(handler, dimensions=768)
    with caplog.at_level("ERROR", logger="kb_api.rag_indexer.inference.providers.siliconflow"):
        with pytest.raises(UpstreamServiceError) as caught:
            client.dense.embed_query("dimension probe")
    assert caught.value.error == "balance is insufficient"

    record = next(row for row in caplog.records if row.message == "SiliconFlow dense request failed")
    assert record.operation == "embedding"
    assert record.model == "BAAI/bge-m3"
    assert record.dimensions == 768
    assert record.status_code == 402
    assert not hasattr(record, "response_body")
    assert record.retryable is False
    assert record.error == "balance is insufficient"
    assert not hasattr(record, "api_key")
    assert not hasattr(record, "input")


@pytest.mark.parametrize("failure", [401, 403, 429, "timeout"])
@pytest.mark.usefixtures("task_context")
def test_errors_use_shared_normalization(make_client, failure):
    source = []

    def handler(request):
        if failure == "timeout":
            error = httpx.ReadTimeout("upstream detail", request=request)
            source.append(error)
            raise error
        response = httpx.Response(failure, request=request)
        source.append(httpx.HTTPStatusError("upstream detail", request=request, response=response))
        return response

    client = make_client(handler)
    with pytest.raises(UpstreamServiceError) as caught:
        client.dense.embed_query("q")
    expected = upstream_error("inference", source[0], retryable=False)
    assert caught.value.detail() == expected.detail()
    assert caught.value.status_code == expected.status_code


def test_local_readiness_and_close(make_client):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    client = make_client(handler)
    assert client.ping() and client.ping()
    client.close()
    assert not client.ping()
    assert not client.dense.ready
    assert client.dense._client.is_closed
    assert requests == []


@pytest.mark.parametrize("body", [b"private-document", b"null", b"[]", b"{}"])
def test_invalid_json_envelope(make_client, body):
    _assert_invalid_response(make_client, body)


@pytest.mark.parametrize("data", [
    None, {}, [None], [], [{}],
    [{"index": 0, "embedding": None}],
    [{"index": 0, "embedding": []}],
    [{"index": 0, "embedding": ["private-document"]}],
    [{"index": 0, "embedding": [True]}],
    [{"index": True, "embedding": [0.1]}],
    [{"index": -1, "embedding": [0.1]}],
    [{"index": "0", "embedding": [0.1]}],
    [{"index": 0, "embedding": [0.1]}, {"index": 0, "embedding": [0.2]}],
])
def test_invalid_dense_schema(make_client, data):
    _assert_invalid_response(make_client, json.dumps({"data": data}).encode())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_model_numbers(make_client, value):
    payload = {"data": [{"index": 0, "embedding": [value]}]}
    _assert_invalid_response(make_client, json.dumps(payload).encode())


def _assert_invalid_response(make_client, body):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    client = make_client(handler)
    with pytest.raises(UpstreamServiceError) as caught:
        client.dense.embed_query("private-document")
    assert caught.value.service == "inference"
    assert caught.value.status_code == 502
    assert caught.value.retryable is False
    assert isinstance(caught.value.error, str)
    assert "test-external-key" not in str(caught.value.detail())
    assert len(calls) == 1


@pytest.mark.parametrize("rows, dimensions", [
    ([{"index": 0, "embedding": [0.1]}], None),
    ([{"index": 0, "embedding": [0.1]}, {"index": 0, "embedding": [0.2]}], None),
    ([{"index": 0, "embedding": [0.1]}, {"index": 2, "embedding": [0.2]}], None),
    ([{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2, 0.3]}], None),
    ([{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2]}], 2),
])
def test_incomplete_or_inconsistent_embeddings(make_client, rows, dimensions):
    client = make_client(lambda request: httpx.Response(200, json={"data": rows}), dimensions=dimensions)
    with pytest.raises(UpstreamServiceError) as caught:
        client.dense.embed_documents(["a", "b"])
    assert caught.value.status_code == 502
    assert caught.value.retryable is False


@pytest.mark.parametrize("outcome", ["success", "invalid", "structured_error", "structured_redirect", 402, "timeout"])
@pytest.mark.parametrize("request_id", [None, "provider-real-id"])
def test_external_call_logs_safe_context(make_client, caplog, outcome, request_id, task_context):
    calls = []

    def handler(request):
        calls.append(request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("private-document private-key", request=request)
        headers = {"x-request-id": request_id} if request_id is not None else {}
        body = {"data": [{"index": 0, "embedding": [0.1]}]}
        if outcome in ("structured_error", "structured_redirect"):
            return httpx.Response(302 if outcome == "structured_redirect" else 402, headers=headers, json={
                "service": "inference", "code": "private-key", "message": "private-document", "retryable": False,
            })
        return httpx.Response(402 if outcome == 402 else 200, headers=headers,
                              json=body if outcome == "success" else {"private-key": "private-document"})

    client = make_client(handler)
    with caplog.at_level("INFO", logger="kb_api.rag_indexer.inference.providers.siliconflow"):
        def invoke():
            return client.dense.embed_query("private-document")

        if outcome == "success":
            assert invoke()
        else:
            with pytest.raises(UpstreamServiceError) as caught:
                invoke()
    records = [row for row in caplog.records if row.name == "kb_api.rag_indexer.inference.providers.siliconflow"]
    assert len(records) == 1 and len(calls) == 1
    record = records[0]
    assert record.trace_id == task_context
    assert record.elapsed_ms >= 0
    expected_status = {"timeout": None, "structured_error": 402, "structured_redirect": 302}.get(outcome, 402 if outcome == 402 else 200)
    assert record.status_code == expected_status
    assert record.provider_request_id == (None if outcome == "timeout" else request_id)
    assert record.levelname == ("INFO" if outcome == "success" else "ERROR")
    assert record.error == (None if outcome == "success" else caught.value.error)
    assert not hasattr(record, "api_key")


def test_incomplete_response_with_valid_rows_is_rejected(make_client):
    body = {"status": "incomplete", "data": [{"index": 0, "embedding": [0.1]}]}
    _assert_invalid_response(make_client, json.dumps(body).encode())
