from contextlib import nullcontext

import pytest

from kb_api.rag_retriever.common.config import SearchConfig
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.schemas import SearchRequest
from kb_api.rag_retriever.service import Retriever


pytestmark = pytest.mark.unit


def test_retriever_closes_vector_and_inference():
    closed = []

    class Component:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    retriever = Retriever(SearchConfig(), Component("vector"), Component("inference"))

    retriever.close()

    assert closed == ["vector", "inference"]


def test_retriever_preserves_dependency_error_fields():
    class DependencyError(Exception):
        service = "vector"
        error = "temporarily unavailable"
        retryable = True
        status_code = 503

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
            raise DependencyError()

        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return []

    inference = type("Inference", (), {"rerank": None})()
    retriever = Retriever(SearchConfig(), Vector(), inference)

    with pytest.raises(UpstreamServiceError) as caught:
        retriever.search(SearchRequest(query="test", app_id="imsdom", workspace_ids=["workspace-1"]))

    assert caught.value.service == "vector"
    assert caught.value.error == "temporarily unavailable"
    assert caught.value.retryable is True
    assert caught.value.status_code == 503


def test_retriever_searches_one_app_collection_for_multiple_workspaces():
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
    retriever = Retriever(SearchConfig(), Vector(), inference)

    retriever.search(SearchRequest(
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
