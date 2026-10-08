from contextlib import nullcontext

import pytest

import kb_api.rag_search.service as service_module
from kb_api.rag_search.common.config import SearchConfig
from kb_api.rag_search.common.upstream import UpstreamServiceError
from kb_api.rag_search.schemas import SearchRequest
from kb_api.rag_search.service import SearchService, SearchRequestError


pytestmark = pytest.mark.unit


def test_search_service_closes_vector_and_inference():
    closed = []

    class Component:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    search_service = SearchService(SearchConfig(), Component("vector"), Component("inference"))

    search_service.close()

    assert closed == ["vector", "inference"]


def test_search_service_preserves_dependency_error_fields():
    error = UpstreamServiceError(
        service="vector", error="temporarily unavailable", retryable=True, status_code=503,
    )

    class Vector:
        def supports_sparse_vector(self):
            return False

        def app_collection_exists(self, app_id):
            return True

        def app_scope(self, app_id):
            return nullcontext()

        def build_metadata_filter(self, file_ids, workspace_ids):
            return None

        def encode_dense_query(self, query):
            raise error

        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return []

    inference = type("Inference", (), {"rerank": None})()
    search_service = SearchService(SearchConfig(), Vector(), inference)

    with pytest.raises(UpstreamServiceError) as caught:
        search_service.search(SearchRequest(query="test", app_id="imsdom", workspace_ids=["workspace-1"]))

    assert caught.value.service == "vector"
    assert caught.value is error
    assert caught.value.error == "temporarily unavailable"
    assert caught.value.retryable is True
    assert caught.value.status_code == 503


def test_search_service_searches_one_app_collection_for_multiple_workspaces():
    calls = []

    class Vector:
        def supports_sparse_vector(self):
            return False

        def app_collection_exists(self, app_id):
            calls.append(("exists", app_id))
            return True

        def app_scope(self, app_id):
            calls.append(("scope", app_id))
            return nullcontext()

        def build_metadata_filter(self, file_ids, workspace_ids):
            calls.append(("filter", file_ids, workspace_ids))
            return "workspace-filter"

        def encode_dense_query(self, query):
            return [0.1]

        def query_dense_vector(self, query_vector, limit, metadata_filter):
            calls.append(("query", metadata_filter))
            return []

    inference = type("Inference", (), {"rerank": None})()
    search_service = SearchService(SearchConfig(), Vector(), inference)

    search_service.search(SearchRequest(
        query="test",
        app_id="imsdom",
        workspace_ids=["workspace-1", "workspace-2"],
    ))

    assert calls.count(("scope", "imsdom")) == 1
    assert ("filter", None, ["workspace-1", "workspace-2"]) in calls
    assert calls.count(("query", "workspace-filter")) == 1


def test_search_request_rejects_empty_workspace_ids():
    with pytest.raises(ValueError, match="workspace_ids"):
        SearchRequest(query="test", app_id="imsdom", workspace_ids=[])


def test_sparse_search_without_provider_raises_neutral_request_error():
    class Vector:
        def supports_sparse_vector(self):
            return False

    inference = type("Inference", (), {"rerank": None})()
    search_service = SearchService(SearchConfig(), Vector(), inference)

    with pytest.raises(SearchRequestError) as caught:
        search_service.search(SearchRequest(
            query="test", app_id="imsdom", workspace_ids=["workspace-1"], mode="sparse",
        ))

    assert isinstance(caught.value, ValueError)
    assert caught.value.status_code == 400
    assert caught.value.detail == "sparse search is not configured"


def test_load_search_service_supports_postgres(monkeypatch):
    vector_config = type("VectorConfig", (), {
        "provider": "postgres", "bm25": True,
        "database_url": "postgresql://rag:rag@postgres:5432/rag",
        "timeout": 30, "query_timeout": 10, "init_timeout": 120,
        "drop_timeout": 180, "retry": None,
    })()
    inference = type("Inference", (), {"dense": object(), "rerank": None, "close": lambda self: None})()
    monkeypatch.setattr(service_module, "load_vector_config", lambda path: vector_config)
    monkeypatch.setattr(service_module, "load_search_config", lambda path: SearchConfig())
    monkeypatch.setattr(service_module, "load_inference_config", lambda path: object())
    monkeypatch.setattr(service_module, "load_inference_components", lambda config: inference)

    loaded = service_module.load_search_service()

    assert loaded.vector.backend_name == "postgres"
    assert loaded.vector.database_url == vector_config.database_url
