import logging
from threading import Barrier
from contextlib import nullcontext
import pytest

import kb_api.rag_retriever.core.search as search_mod
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.core.scope import app_collection, current_collection
from kb_api.rag_retriever.core.search import SearchPlan, _SearchExecutor
from kb_api.rag_retriever.schemas import SearchRequest


pytestmark = pytest.mark.unit


def test_dense_search_uses_top_k_without_rerank_fetch_limit():
    request = SearchRequest(
        query="query",
        app_id="imsdom",
        workspace_ids=["workspace-a"],
        top_k=50,
        rerank=False,
        rerank_fetch_k=20,
    )
    plan = SearchPlan(request.query, top_k=request.top_k, rerank=False, rerank_fetch_k=request.rerank_fetch_k)
    vector = FakeVector()

    results = _SearchExecutor(plan, vector=vector).execute()

    assert results
    assert ("search_dense", "query", 50, ("metadata-filter", (), ())) in vector.calls


class FakeVector:
    def __init__(self, total_chunks=100):
        self.total_chunks = total_chunks
        self.calls = []

    def get_total_chunks(self, file_ids=None):
        self.calls.append(("get_total_chunks", tuple(file_ids or [])))
        return self.total_chunks

    def build_metadata_filter(self, file_ids=None, workspace_ids=None):
        self.calls.append(("build_metadata_filter", tuple(file_ids or []), tuple(workspace_ids or [])))
        return ("metadata-filter", tuple(file_ids or []), tuple(workspace_ids or []))

    def app_collection_exists(self, app_id):
        self.calls.append(("app_collection_exists", app_id))
        return True

    def app_scope(self, app_id):
        self.calls.append(("app_scope", app_id))
        return nullcontext()

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]


class FakeTracedVector(FakeVector):
    def encode_dense_query(self, query):
        self.calls.append(("encode_dense_query", query))
        return [0.1, 0.2, 0.3]

    def query_dense_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
        return [{"id": "dense-1", "content": "dense", "metadata": {}, "_score": 0.8}]


class FakeSparseVector(FakeTracedVector):
    def encode_sparse_query(self, query):
        self.calls.append(("encode_sparse_query", query))
        return {1: 0.5}

    def query_sparse_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_sparse_vector", query_vector, limit, metadata_filter))
        return [{"id": "sparse-1", "content": "sparse", "metadata": {}, "_score": 0.7}]


class FakeRerank:
    def __init__(self):
        self.calls = []

    def rerank(self, query, items, top_k):
        self.calls.append((query, [item["id"] for item in items], top_k))
        ranked = list(reversed(items))
        for index, item in enumerate(ranked):
            item["_score"] = 1.0 - index * 0.1
        return ranked[:top_k]


def test_search_plan_uses_file_ids():
    plan = search_mod.SearchPlan("query", file_ids=["file_a", "file_b"])

    assert plan.file_ids == ["file_a", "file_b"]


def test_search_plan_uses_workspace_ids():
    plan = search_mod.SearchPlan("query", workspace_ids=["workspace_a", "workspace_b"])

    assert plan.workspace_ids == ["workspace_a", "workspace_b"]


def test_search_plan_rejects_empty_file_ids():
    with pytest.raises(ValueError, match="file_ids cannot be empty"):
        search_mod.SearchPlan("query", file_ids=[])


def test_search_plan_limits_file_ids_to_1000():
    with pytest.raises(ValueError, match="file_ids exceeds max limit: 1000"):
        search_mod.SearchPlan("query", file_ids=[f"f{i}" for i in range(1001)])


def test_executor_searches_single_chunks_collection_with_file_filter():
    vector = FakeVector()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=5, file_ids=["file_a"]),
        vector=vector,
    ).execute()

    assert [item["id"] for item in results] == ["dense-1"]
    assert ("build_metadata_filter", ("file_a",), ()) in vector.calls
    assert ("search_dense", "query", 5, ("metadata-filter", ("file_a",), ())) in vector.calls


def test_executor_exposes_retrieval_score():
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=1),
        vector=FakeVector(),
    ).execute()

    assert results[0]["score"] == 0.8
    assert "_score" not in results[0]


def test_executor_runs_search_stages_in_order(monkeypatch):
    executor = _SearchExecutor(SearchPlan("query"), vector=FakeVector())
    calls = []
    context = {"retrieve_limit": 5, "metadata_filter": None}
    items = [{"id": "a", "content": "text", "metadata": {}, "_score": 0.8}]

    def prepare():
        calls.append("prepare")
        return context

    def retrieve(value):
        assert value == context
        calls.append("retrieve")
        return items

    def stage(name):
        def run(value):
            assert value == items
            calls.append(name)
            return value
        return run

    monkeypatch.setattr(executor, "_prepare_plan", prepare)
    monkeypatch.setattr(executor, "_retrieve_items", retrieve)
    monkeypatch.setattr(executor, "_dedupe_items", stage("dedupe"))
    monkeypatch.setattr(executor, "_rerank_items", stage("rerank"))
    monkeypatch.setattr(executor, "_format_response", stage("format"))

    assert executor.execute() == items
    assert calls == ["prepare", "retrieve", "dedupe", "rerank", "format"]


def test_dense_search_splits_query_embedding_and_vector_query():
    vector = FakeTracedVector()
    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2),
        vector=vector,
    )

    assert [item["id"] for item in executor.execute()] == ["dense-1"]

    assert vector.calls == [
        ("build_metadata_filter", (), ()),
        ("encode_dense_query", "query"),
        ("query_dense_vector", [0.1, 0.2, 0.3], 2, ("metadata-filter", (), ())),
    ]


def test_executor_uses_sparse_search_mode():
    vector = FakeSparseVector()
    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="sparse"),
        vector=vector,
    )

    assert [item["id"] for item in executor.execute()] == ["sparse-1"]
    assert ("query_sparse_vector", {1: 0.5}, 2, ("metadata-filter", (), ())) in vector.calls


def test_executor_hybrid_merges_dense_and_sparse_results():
    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
            return [{"id": "shared", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            self.calls.append(("query_sparse_vector", query_vector, limit, metadata_filter))
            return [
                {"id": "shared", "content": "dense", "metadata": {}, "_score": 0.4},
                {"id": "sparse-only", "content": "sparse", "metadata": {}, "_score": 0.9},
            ]

    vector = Vector()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid", rrf_k=60),
        vector=vector,
    ).execute()

    assert [item["id"] for item in results] == ["shared", "sparse-only"]
    assert results[0]["score"] == pytest.approx(2 / 61)


def test_executor_hybrid_runs_dense_and_sparse_in_parallel():
    concurrent_queries = Barrier(2, timeout=5)

    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            concurrent_queries.wait()
            return [{"id": "dense", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            concurrent_queries.wait()
            return [{"id": "sparse", "content": "sparse", "metadata": {}, "_score": 0.7}]

    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
        vector=Vector(),
    ).execute()

    assert {item["id"] for item in results} == {"dense", "sparse"}


def test_executor_hybrid_preserves_app_collection_scope_in_parallel_threads():
    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "dense", "content": current_collection(), "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "sparse", "content": current_collection(), "metadata": {}, "_score": 0.7}]

    with app_collection("imsdom"):
        results = search_mod._SearchExecutor(
            search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
            vector=Vector(),
        ).execute()

    assert {item["content"] for item in results} == {"imsdom_chunks"}


def test_executor_hybrid_falls_back_to_dense_when_sparse_upstream_fails():
    class Vector(FakeSparseVector):
        def query_dense_vector(self, query_vector, limit, metadata_filter):
            return [{"id": "dense", "content": "dense", "metadata": {}, "_score": 0.8}]

        def query_sparse_vector(self, query_vector, limit, metadata_filter):
            raise UpstreamServiceError(
                service="inference",
                error="inference returned HTTP 404",
                retryable=False,
                status_code=502,
            )

    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, mode="hybrid"),
        vector=Vector(),
    ).execute()

    assert [item["id"] for item in results] == ["dense"]


def test_executor_reranks_dense_candidates_when_rerank_client_is_configured():
    class Vector(FakeVector):
        def search_dense(self, query, limit, metadata_filter):
            self.calls.append(("search_dense", query, limit, metadata_filter))
            return [
                {"id": "a", "content": "a", "metadata": {}, "_score": 0.1},
                {"id": "b", "content": "b", "metadata": {}, "_score": 0.2},
                {"id": "c", "content": "c", "metadata": {}, "_score": 0.3},
            ][:limit]

    vector = Vector()
    rerank = FakeRerank()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, rerank_fetch_k=3, rerank=True),
        vector=vector,
        rerank=rerank,
    ).execute()

    assert [item["id"] for item in results] == ["c", "b"]
    assert ("search_dense", "query", 3, ("metadata-filter", (), ())) in vector.calls
    assert rerank.calls == [("query", ["a", "b", "c"], 2)]


def test_executor_skips_rerank_when_no_candidates():
    class Vector(FakeVector):
        def search_dense(self, query, limit, metadata_filter):
            return []

    rerank = FakeRerank()
    results = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=3, rerank=True),
        vector=Vector(),
        rerank=rerank,
    ).execute()

    assert results == []
    assert rerank.calls == []


def test_executor_returns_retrieved_items_when_rerank_fails(caplog):
    class Vector(FakeVector):
        def search_dense(self, query, limit, metadata_filter):
            return [
                {"id": "a", "content": "a", "metadata": {}, "_score": 0.1},
                {"id": "b", "content": "b", "metadata": {}, "_score": 0.2},
                {"id": "c", "content": "c", "metadata": {}, "_score": 0.3},
            ][:limit]

    class FailingRerank:
        def rerank(self, query, items, top_k):
            raise UpstreamServiceError(
                service="inference",
                error="inference returned HTTP 503",
                retryable=True,
                status_code=503,
            )

    executor = search_mod._SearchExecutor(
        search_mod.SearchPlan("query", top_k=2, rerank_fetch_k=3, rerank=True),
        vector=Vector(),
        rerank=FailingRerank(),
    )

    with caplog.at_level(logging.WARNING):
        results = executor.execute()

    assert [item["id"] for item in results] == ["c", "b"]
    assert any(record.message == "rerank failed, return retrieved items" for record in caplog.records)
