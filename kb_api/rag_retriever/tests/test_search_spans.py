from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.core.search import pipeline


@pytest.fixture
def spans(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(__name__)
    monkeypatch.setattr(pipeline, "tracer", tracer, raising=False)
    yield tracer, exporter
    provider.shutdown()


class Vector:
    dense = SimpleNamespace(model="dense-model")
    sparse = SimpleNamespace(model="sparse-model")

    def build_metadata_filter(self, file_ids, workspace_ids):
        return workspace_ids

    def encode_dense_query(self, query):
        return [0.1, 0.2]

    def encode_sparse_query(self, query):
        return {1: 0.5}

    def query_dense_vector(self, vector, limit, metadata_filter):
        return [{"id": "dense", "content": "private document", "_score": 0.9}]

    def query_sparse_vector(self, vector, limit, metadata_filter):
        return [{"id": "sparse", "content": "private document", "_score": 0.8}]


class Rerank:
    model = "rerank-model"

    def rerank(self, query, items, top_k):
        return items[:top_k]


def assert_private(spans):
    for span in spans:
        exported = span.to_json()
        for secret in ("private query", "private document", "password=secret", "https://private"):
            assert secret not in exported


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
def test_search_spans_inherit_entry_context_and_record_stages(spans, mode):
    tracer, exporter = spans
    plan = pipeline.SearchPlan("private query", app_id="app", workspace_ids=["workspace"], mode=mode, top_k=2, rerank=True)
    with tracer.start_as_current_span("entry") as entry:
        result = pipeline._SearchExecutor(plan, Vector(), Rerank()).execute()
    finished = exporter.get_finished_spans()
    by_name = {span.name: span for span in finished}
    assert "rag.search" in by_name
    root = by_name["rag.search"]
    assert root.parent.span_id == entry.get_span_context().span_id
    assert root.attributes["app_id"] == "app"
    assert root.attributes["workspace_ids"] == ("workspace",)
    assert root.attributes["mode"] == mode
    assert root.attributes["top_k"] == 2
    assert root.attributes["result_count"] == len(result)
    kinds = ("dense", "sparse") if mode == "hybrid" else (mode,)
    for kind in kinds:
        for stage in ("embedding", "query"):
            span = by_name[f"rag.search.{kind}.{stage}"]
            assert span.parent.span_id == root.context.span_id
            assert span.context.trace_id == root.context.trace_id
        assert by_name[f"rag.search.{kind}.embedding"].attributes["model"] == f"{kind}-model"
        assert by_name[f"rag.search.{kind}.query"].attributes["result_count"] == 1
    for name in ("rag.search.dedupe", "rag.search.rerank"):
        assert by_name[name].parent.span_id == root.context.span_id
        assert by_name[name].attributes["result_count"] == len(result)
    assert by_name["rag.search.rerank"].attributes["model"] == "rerank-model"
    if mode == "hybrid":
        assert by_name["rag.search.fusion"].attributes["result_count"] == 2
    assert root.status.status_code != StatusCode.ERROR
    assert_private(finished)


@pytest.mark.parametrize("failure", ["sparse", "rerank"])
def test_fallback_marks_child_error_without_failing_search(spans, failure):
    _, exporter = spans
    error = UpstreamServiceError(service="inference", error="https://private password=secret", retryable=True, status_code=503)

    class FailingVector(Vector):
        def query_sparse_vector(self, *args):
            raise error

    class FailingRerank(Rerank):
        def rerank(self, *args):
            raise error

    plan = pipeline.SearchPlan("private query", mode="hybrid" if failure == "sparse" else "dense", rerank=failure == "rerank")
    result = pipeline._SearchExecutor(plan, FailingVector() if failure == "sparse" else Vector(), FailingRerank()).execute()
    assert [item["id"] for item in result] == ["dense"]
    by_name = {span.name: span for span in exporter.get_finished_spans()}
    failed = by_name["rag.search.sparse.query" if failure == "sparse" else "rag.search.rerank"]
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.attributes["error.type"] == "UpstreamServiceError"
    assert by_name["rag.search"].status.status_code != StatusCode.ERROR
    assert_private(exporter.get_finished_spans())


def test_unhandled_embedding_error_marks_search_and_preserves_exception(spans):
    _, exporter = spans
    error = RuntimeError("private query password=secret")

    class FailingVector(Vector):
        def encode_dense_query(self, query):
            raise error

    with pytest.raises(RuntimeError) as raised:
        pipeline._SearchExecutor(pipeline.SearchPlan("private query"), FailingVector()).execute()
    assert raised.value is error
    by_name = {span.name: span for span in exporter.get_finished_spans()}
    assert by_name["rag.search.dense.embedding"].status.status_code == StatusCode.ERROR
    assert by_name["rag.search"].status.status_code == StatusCode.ERROR
    assert trace.get_current_span().get_span_context().is_valid is False
    assert_private(exporter.get_finished_spans())


def test_noop_tracer_keeps_search_results(monkeypatch):
    monkeypatch.setattr(pipeline, "tracer", trace.NoOpTracer())
    results = pipeline._SearchExecutor(pipeline.SearchPlan("private query", mode="hybrid"), Vector()).execute()
    assert {item["id"] for item in results} == {"dense", "sparse"}


@pytest.mark.parametrize("items", [[], [
    {"id": "a", "content": "private document", "_score": 0.9},
    {"id": "a", "content": "private document", "_score": 0.8},
    {"id": "b", "content": "private document", "_score": 0.7},
]])
def test_dedupe_and_final_top_k_record_distinct_counts(spans, items):
    _, exporter = spans

    class DuplicateVector(Vector):
        def query_dense_vector(self, *args):
            return items

    results = pipeline._SearchExecutor(pipeline.SearchPlan("private query", top_k=1), DuplicateVector()).execute()
    by_name = {span.name: span for span in exporter.get_finished_spans()}
    assert by_name["rag.search.dedupe"].attributes["input_count"] == len(items)
    assert by_name["rag.search.dedupe"].attributes["result_count"] == len({item["id"] for item in items})
    assert by_name["rag.search"].attributes["result_count"] == len(results) == min(len(items), 1)
