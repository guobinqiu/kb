from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kb_api.rag_indexer.clients.vector import milvus, qdrant
from kb_api.rag_indexer.core.scope import app_collection
from kb_api.rag_indexer.common import deadline
from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from contextvars import ContextVar
from kb_api.rag_indexer.core.scope import current_collection
from kb_api.rag_indexer.common.config import RetryConfig
from pymilvus.decorators import retry_on_rpc_failure
from pymilvus.exceptions import ErrorCode, MilvusException
import grpc
from pymilvus.decorators import retry_on_schema_mismatch
from pymilvus.exceptions import DataNotMatchException
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import httpx
from qdrant_client.common.client_exceptions import ResourceExhaustedResponse
from qdrant_client.http.exceptions import ResponseHandlingException


pytestmark = pytest.mark.unit
CHUNKS = [{"id": "chunk-1", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}}]


def make_vector(backend, events, after):
    def call(name, result):
        def invoke(*args, **kwargs):
            events.append(name)
            after(name)
            return result
        return Mock(side_effect=invoke)

    dense = SimpleNamespace(embed_documents=call("dense", [[0.1, 0.2]]))
    cls = milvus.MilvusVectorClient if backend == "milvus" else qdrant.QdrantVectorClient
    vector = cls(dense=dense, timeout=30)
    sdk = Mock()
    sdk.has_collection.return_value = False
    sdk.upsert = call("upsert", None)
    sdk.flush = call("flush", None)
    sdk.query = call("query", [{"pk": "old"}])
    sdk.count = call("count", SimpleNamespace(count=1))
    sdk.delete = call("delete", None)
    vector.client = sdk
    return vector


@pytest.mark.parametrize("failure", [None, "dense"])
def test_qdrant_index_embedding_preserves_request_context(failure):

    trace = ContextVar("test_trace")
    error = RuntimeError("embedding failed")
    vector = make_vector("qdrant", [], lambda name: None)

    def embed(name, result):
        assert current_collection() == "test_chunks"
        assert trace.get() == "index-trace"
        assert 0 < deadline.request_timeout(30) <= 10
        if name == failure:
            raise error
        return result

    vector.dense.embed_documents.side_effect = lambda texts: embed("dense", [[0.1, 0.2]])
    token = trace.set("index-trace")
    try:
        with app_collection("test"), deadline.index_deadline(10):
            if failure:
                with pytest.raises(RuntimeError) as raised:
                    vector.add_file_chunks(CHUNKS, "file")
                assert raised.value is error
                vector.client.upsert.assert_not_called()
            else:
                assert vector.add_file_chunks(CHUNKS, "file") == 1
                vector.client.upsert.assert_called_once()
    finally:
        trace.reset(token)
    vector.dense.embed_documents.assert_called_once_with(["hello"])


@pytest.mark.parametrize("backend,stages", [
    ("milvus", ["dense", "upsert", "query", "delete"]),
    ("qdrant", ["dense", "upsert", "count", "delete"]),
])
def test_index_stops_after_each_expired_stage(monkeypatch, backend, stages):
    now = [0.0]
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now[0])
    for stop in range(len(stages)):
        now[0] = 0.0
        events = []

        def expire(name):
            if len(events) == stop + 1:
                now[0] = 10.0

        vector = make_vector(backend, events, expire)
        with app_collection("test"), deadline.index_deadline(5):
            with pytest.raises(UpstreamServiceError) as raised:
                vector.add_file_chunks(CHUNKS, "file")
        assert raised.value.retryable is False
        assert events == stages[:stop + 1]
        assert vector._document_lock("file").acquire(blocking=False)
        vector._document_lock("file").release()


@pytest.mark.parametrize("backend,stages", [
    ("milvus", ["dense", "upsert", "query", "delete"]),
    ("qdrant", ["dense", "upsert", "count", "delete"]),
])
def test_index_propagates_original_failure_without_retry(backend, stages):
    for stop in stages:
        events = []
        error = RuntimeError(stop)

        def fail(name):
            if name == stop:
                raise error

        vector = make_vector(backend, events, fail)
        with app_collection("test"), pytest.raises(RuntimeError) as raised:
            vector.add_file_chunks(CHUNKS, "file")
        assert raised.value is error
        assert events == stages[:stages.index(stop) + 1]


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_vector_write_retries_after_embeddings_without_reembedding(monkeypatch, backend):

    monkeypatch.setattr("kb_api.rag_indexer.common.retry.time.sleep", lambda seconds: None)
    events = []
    error = UpstreamServiceError(service="vector", error="temporary", retryable=True, status_code=503)

    def fail_once(name):
        if name == "upsert" and events.count("upsert") == 1:
            raise error

    vector = make_vector(backend, events, fail_once)
    vector.retry = RetryConfig(max_attempts=3, interval_seconds=0.5)
    with app_collection("test"):
        assert vector.add_file_chunks(CHUNKS, "file") == 1

    assert events.count("dense") == 1
    assert events.count("upsert") == 2


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_expired_empty_index_does_not_clean_up(backend):
    events = []
    vector = make_vector(backend, events, lambda name: None)
    with app_collection("test"), deadline.index_deadline(-1):
        with pytest.raises(UpstreamServiceError):
            vector.add_file_chunks([], "file")
    assert events == []


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_index_clips_sdk_timeouts_and_preserves_ids(monkeypatch, backend):
    monkeypatch.setattr(deadline.time, "monotonic", lambda: 0.0)
    vector = make_vector(backend, [], lambda name: None)
    with app_collection("test"), deadline.index_deadline(3):
        assert vector.add_file_chunks(CHUNKS, "file") == 1
        assert vector.add_file_chunks(CHUNKS, "file") == 1
    sdk = vector.client
    for name in (["upsert", "query", "delete"] if backend == "milvus" else ["upsert", "count", "delete"]):
        for call in getattr(sdk, name).call_args_list:
            assert call.kwargs["timeout"] == 3
            if backend == "milvus":
                assert call.kwargs["retry_times"] == 0
                assert call.kwargs["retry_on_rate_limit"] is False
    first, second = sdk.upsert.call_args_list
    if backend == "milvus":
        assert first.kwargs["data"][0]["pk"] == second.kwargs["data"][0]["pk"] == milvus._point_id("chunk-1")
    else:
        assert first.kwargs["points"][0].id == second.kwargs["points"][0].id == "chunk-1"


@pytest.mark.parametrize("stage", ["count", "delete"])
def test_qdrant_index_does_not_swallow_collection_not_found(stage):
    vector = make_vector("qdrant", [], lambda name: None)
    error = qdrant.UnexpectedResponse(404, "Not Found", b"missing", {})
    getattr(vector.client, stage).side_effect = error
    with app_collection("test"), pytest.raises(qdrant.UnexpectedResponse) as raised:
        vector.add_file_chunks(CHUNKS, "file")
    assert raised.value is error
    assert getattr(vector.client, stage).call_count == 1


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_ensure_app_collection_is_attempted_once(backend):
    error = RuntimeError("unavailable")
    vector = make_vector(backend, [], lambda name: None)
    vector.ensure_collections = Mock(side_effect=error)
    with pytest.raises(RuntimeError) as raised:
        vector.ensure_app_collection("test")
    assert raised.value is error
    vector.ensure_collections.assert_called_once_with("test_chunks")


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_collection_creation_retries_retryable_vector_failures(monkeypatch, backend):

    monkeypatch.setattr("kb_api.rag_indexer.common.retry.time.sleep", lambda seconds: None)
    vector = make_vector(backend, [], lambda name: None)
    vector.dense.vector_size = 2
    vector.retry = RetryConfig(max_attempts=3, interval_seconds=0.5)
    error = UpstreamServiceError(service="vector", error="temporary", retryable=True, status_code=503)
    if backend == "milvus":
        vector.client.create_collection.side_effect = [error, None]
    else:
        vector.client.collection_exists.return_value = False
        vector.client.create_collection.side_effect = [error, None]
        vector.client.get_collection.return_value = object()
        vector.client.count.return_value = SimpleNamespace(count=0)

    vector.ensure_app_collection("test")

    assert vector.client.create_collection.call_count == 2


def test_qdrant_readiness_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(qdrant.time, "sleep", lambda seconds: None)
    sdk = Mock()
    error = RuntimeError("not ready")
    sdk.get_collection.side_effect = [error, None]
    with pytest.raises(RuntimeError) as raised:
        qdrant._wait_collection_ready(sdk, "test_chunks")
    assert raised.value is error
    sdk.get_collection.assert_called_once_with("test_chunks")
    sdk.count.assert_not_called()


def test_qdrant_readiness_passes_timeout_to_count():
    sdk = Mock()

    qdrant._wait_collection_ready(sdk, "test_chunks", timeout=120)

    sdk.get_collection.assert_called_once_with("test_chunks")
    sdk.count.assert_called_once_with(collection_name="test_chunks", exact=True, timeout=120)


def test_milvus_disables_grpc_retries(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr("pymilvus.MilvusClient", constructor)
    milvus.MilvusVectorClient(dense=object())._client()
    assert constructor.call_args.kwargs["grpc_options"]["grpc.enable_retries"] == 0
    assert constructor.call_args.kwargs["dedicated"] is True


def test_milvus_collection_setup_disables_controllable_retries():
    vector = make_vector("milvus", [], lambda name: None)
    vector._collection_schema = Mock(return_value=object())
    vector._collection_index_params = Mock(return_value=object())
    vector.ensure_app_collection("test")
    assert "index_params" not in vector.client.create_collection.call_args.kwargs
    for name in ["has_collection", "create_collection", "create_index", "load_collection"]:
        options = getattr(vector.client, name).call_args.kwargs
        assert options["retry_times"] == 0
        assert options["retry_on_rate_limit"] is False
    assert [call[0] for call in vector.client.mock_calls] == ["has_collection", "create_collection", "create_index", "load_collection"]


def test_installed_pymilvus_rate_limit_retry_is_disabled():

    error = MilvusException(code=ErrorCode.RATE_LIMIT, message="busy")
    operation = Mock(side_effect=error)

    @retry_on_rpc_failure()
    def rpc(self, **kwargs):
        return operation()

    with pytest.raises(MilvusException) as raised:
        rpc(SimpleNamespace(), timeout=30, retry_times=0, retry_on_rate_limit=False)
    assert raised.value is error
    operation.assert_called_once_with()


def test_milvus_index_validation_clips_timeout_and_disables_controllable_retries(monkeypatch):
    monkeypatch.setattr(deadline.time, "monotonic", lambda: 0.0)
    vector = make_vector("milvus", [], lambda name: None)
    vector.client.has_collection.return_value = True
    vector.client.describe_collection.return_value = {
        "fields": [{"name": "sparse_vector"}],
        "functions": [{"name": "text_bm25"}],
    }
    with app_collection("test"), deadline.index_deadline(3):
        vector.add_file_chunks(CHUNKS, "file")
    for name in ["has_collection", "describe_collection"]:
        options = getattr(vector.client, name).call_args.kwargs
        assert options["timeout"] == 3
        assert options["retry_times"] == 0
        assert options["retry_on_rate_limit"] is False


def test_installed_pymilvus_timeout_overrides_zero_retry_count(monkeypatch):

    class Unavailable(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

    monkeypatch.setattr("pymilvus.decorators.time.sleep", lambda seconds: None)
    error = MilvusException(message="second attempt")
    operation = Mock(side_effect=[Unavailable(), error])

    @retry_on_rpc_failure()
    def rpc(self, **kwargs):
        return operation()

    with pytest.raises(MilvusException) as raised:
        rpc(SimpleNamespace(), timeout=30, retry_times=0, retry_on_rate_limit=False)
    assert raised.value is error
    assert operation.call_count == 2


def test_installed_pymilvus_schema_mismatch_retries_without_switch():

    error = RuntimeError("second attempt")
    operation = Mock(side_effect=[DataNotMatchException(message="schema"), error])

    @retry_on_schema_mismatch()
    def rpc(self, collection_name, **kwargs):
        return operation()

    handler = Mock()
    with pytest.raises(RuntimeError) as raised:
        rpc(handler, "test", context=Mock(), retry_times=0, retry_on_rate_limit=False)
    assert raised.value is error
    assert operation.call_count == 2
    handler._invalidate_schema.assert_called_once()


def test_installed_qdrant_rest_default_transport_has_no_retries():
    vector = qdrant.QdrantVectorClient(dense=object())
    try:
        sdk = vector._client()
        assert sdk._client._prefer_grpc is False
        assert sdk._client.openapi_client.client._client._transport._pool._retries == 0
    finally:
        vector.close()


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_index_waiting_for_document_lock_checks_deadline_before_model(monkeypatch, backend):

    now = [0.0]
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now[0])
    events = []
    vector = make_vector(backend, events, lambda name: None)

    @contextmanager
    def delayed_lock(file_id):
        now[0] = 10.0
        yield

    monkeypatch.setattr(vector, "_document_lock", delayed_lock)
    with app_collection("test"), deadline.index_deadline(5), pytest.raises(UpstreamServiceError):
        vector.add_file_chunks(CHUNKS, "file")
    assert events == []


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_document_locks_serialize_same_file_and_allow_other_files(backend):

    vector = make_vector(backend, [], lambda name: None)
    entered = Event()
    attempting = Event()

    def write():
        with app_collection("test"):
            attempting.set()
            result = vector.add_file_chunks(CHUNKS, "file")
            entered.set()
            return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        with vector._document_lock("file"):
            future = executor.submit(write)
            assert attempting.wait(2)
            assert not entered.wait(0.05)
            assert vector._document_lock("other").acquire(blocking=False)
            vector._document_lock("other").release()
        assert future.result(timeout=2) == 1
    assert entered.is_set()


@pytest.mark.parametrize("response_kind", ["connection_error", "rate_limit"])
def test_installed_qdrant_upsert_does_not_retry_http_failures(response_kind):

    calls = []

    def send(request):
        calls.append(request)
        if response_kind == "connection_error":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"status": {"error": "busy"}})

    sdk = qdrant.QdrantClient(url="http://localhost:6333", check_compatibility=False, transport=httpx.MockTransport(send))
    try:
        with pytest.raises((ResourceExhaustedResponse, ResponseHandlingException)):
            sdk.upsert("test_chunks", points=[qdrant.models.PointStruct(id=1, vector=[0.1])])
    finally:
        sdk.close()
    assert len(calls) == 1


def test_qdrant_subsecond_timeout_is_positive_and_stops_next_stage(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now[0])
    events = []

    def expire(name):
        if name == "upsert":
            now[0] = 1.0

    vector = make_vector("qdrant", events, expire)
    with app_collection("test"), deadline.index_deadline(0.25), pytest.raises(UpstreamServiceError):
        vector.add_file_chunks(CHUNKS, "file")
    assert vector.client.upsert.call_args.kwargs["timeout"] == 1
    vector.client.count.assert_not_called()


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_index_without_configured_timeout_still_uses_deadline(monkeypatch, backend):
    monkeypatch.setattr(deadline.time, "monotonic", lambda: 0.0)
    vector = make_vector(backend, [], lambda name: None)
    vector.timeout = None
    with app_collection("test"), deadline.index_deadline(3):
        assert vector.add_file_chunks(CHUNKS, "file") == 1
    assert vector.client.upsert.call_args.kwargs["timeout"] == 3


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_index_without_configured_timeout_has_finite_default(backend):
    vector = make_vector(backend, [], lambda name: None)
    vector.timeout = None
    with app_collection("test"):
        assert vector.add_file_chunks(CHUNKS, "file") == 1
    assert vector.client.upsert.call_args.kwargs["timeout"] == 30
