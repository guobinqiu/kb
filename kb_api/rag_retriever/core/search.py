"""Search plan and execution pipeline."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.clients.vector.base import VectorClient


logger = logging.getLogger("kb_api.rag_retriever.core.search.pipeline")
tracer = trace.get_tracer("kb_api.rag_retriever.core.search.pipeline")


@contextmanager
def _search_span(name: str, attributes: dict | None = None):
    with tracer.start_as_current_span(name, attributes=attributes, record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR)
            span.set_attribute("error.type", type(exc).__name__)
            span.add_event("exception", {"exception.type": type(exc).__name__})
            raise


def _model_attributes(client) -> dict:
    model = getattr(client, "model", None)
    return {"model": model} if isinstance(model, str) else {}


@dataclass(frozen=True)
class SearchPlan:
    query: str
    app_id: str | None = None
    mode: str = "dense"
    top_k: int = 5
    rerank_fetch_k: int | None = None
    rerank: bool = False
    rrf_k: int = 60
    file_ids: list[str] | None = None
    workspace_ids: list[str] | None = None

    def __post_init__(self):
        if self.mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("mode must be dense, sparse, or hybrid")
        if self.rerank and self.rerank_fetch_k is not None and self.rerank_fetch_k < self.top_k:
            raise ValueError("rerank_fetch_k must be >= top_k")
        if self.file_ids is not None:
            if len(self.file_ids) == 0:
                raise ValueError("file_ids cannot be empty")
            if len(self.file_ids) > 1000:
                raise ValueError("file_ids exceeds max limit: 1000")
        if self.workspace_ids is not None and len(self.workspace_ids) == 0:
            raise ValueError("workspace_ids cannot be empty")


class _SearchExecutor:
    def __init__(
        self,
        plan: SearchPlan,
        vector: VectorClient,
        rerank: Any = None,
    ):
        self.plan = plan
        self.vector_client = vector
        self.rerank_client = rerank
        self.elapsed_ms = 0.0
        if self.plan.rerank and self.rerank_client is None:
            raise ValueError("rerank is enabled but inference rerank client is not configured")

    def execute(self) -> list[dict]:
        started_at = time.perf_counter()
        try:
            attributes = {
                "mode": self.plan.mode, "top_k": self.plan.top_k,
                "workspace_ids": list(self.plan.workspace_ids or []), "rerank": self.plan.rerank,
            }
            if self.plan.app_id is not None:
                attributes["app_id"] = self.plan.app_id
            with _search_span("rag.search", attributes) as span:
                context = self._prepare_plan()
                items = self._retrieve_items(context)
                items = self._dedupe_items(items)
                items = self._rerank_items(items)
                results = self._format_response(items)
                span.set_attribute("result_count", len(results))
                return results
        finally:
            self.elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)

    def _prepare_plan(self):
        retrieve_limit = self.plan.rerank_fetch_k if self.plan.rerank and self.plan.rerank_fetch_k is not None else self.plan.top_k
        return {
            "retrieve_limit": retrieve_limit,
            "metadata_filter": self.vector_client.build_metadata_filter(self.plan.file_ids, self.plan.workspace_ids),
        }

    def _retrieve_items(self, context: dict[str, Any]) -> list[dict]:
        if self.plan.mode == "sparse":
            items = _retrieve_sparse(self.vector_client, context["metadata_filter"], self.plan.query, context["retrieve_limit"])
        elif self.plan.mode == "hybrid":
            items = _retrieve_hybrid(
                self.vector_client,
                context["metadata_filter"],
                self.plan.query,
                context["retrieve_limit"],
                self.plan.rrf_k,
            )
        else:
            items = _retrieve_dense(self.vector_client, context["metadata_filter"], self.plan.query, context["retrieve_limit"])
        return [dict(item) for item in items]

    def _dedupe_items(self, items: list[dict]) -> list[dict]:
        with _search_span("rag.search.dedupe", {"input_count": len(items)}) as span:
            results = _dedupe(items)
            span.set_attribute("result_count", len(results))
            return results

    def _rerank_items(self, items: list[dict]) -> list[dict]:
        if not self.plan.rerank or not items:
            return items
        try:
            attributes = {"input_count": len(items), "top_k": self.plan.top_k, **_model_attributes(self.rerank_client)}
            with _search_span("rag.search.rerank", attributes) as span:
                results = self.rerank_client.rerank(self.plan.query, items, self.plan.top_k)
                span.set_attribute("result_count", len(results))
                return results
        except Exception as exc:
            logger.warning("rerank failed, return retrieved items", exc_info=exc)
            return items

    def _format_response(self, items: list[dict]) -> list[dict]:
        items.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
        return [_public_item(item) for item in items[: self.plan.top_k]]


def _retrieve_dense(vector: VectorClient, metadata_filter, query: str, limit: int) -> list[dict]:
    if hasattr(vector, "encode_dense_query") and hasattr(vector, "query_dense_vector"):
        with _search_span("rag.search.dense.embedding", _model_attributes(getattr(vector, "dense", None))) as span:
            query_vector = vector.encode_dense_query(query)
            span.set_attribute("vector_count", 1)
        with _search_span("rag.search.dense.query", {"limit": limit}) as span:
            results = vector.query_dense_vector(query_vector, limit, metadata_filter)
            span.set_attribute("result_count", len(results))
            return results
    with _search_span("rag.search.dense.query", {"limit": limit}) as span:
        results = vector.search_dense(query, limit, metadata_filter)
        span.set_attribute("result_count", len(results))
        return results


def _retrieve_sparse(vector: VectorClient, metadata_filter, query: str, limit: int) -> list[dict]:
    if hasattr(vector, "encode_sparse_query") and hasattr(vector, "query_sparse_vector"):
        with _search_span("rag.search.sparse.embedding", _model_attributes(getattr(vector, "sparse", None))) as span:
            query_vector = vector.encode_sparse_query(query)
            span.set_attribute("vector_count", 1)
        with _search_span("rag.search.sparse.query", {"limit": limit}) as span:
            results = vector.query_sparse_vector(query_vector, limit, metadata_filter)
            span.set_attribute("result_count", len(results))
            return results
    with _search_span("rag.search.sparse.query", {"limit": limit}) as span:
        results = vector.search_sparse(query, limit, metadata_filter)
        span.set_attribute("result_count", len(results))
        return results


def _retrieve_hybrid(
    vector: VectorClient,
    metadata_filter,
    query: str,
    limit: int,
    rrf_k: int,
) -> list[dict]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        dense_future = executor.submit(copy_context().run, _retrieve_dense, vector, metadata_filter, query, limit)
        sparse_future = executor.submit(copy_context().run, _retrieve_sparse, vector, metadata_filter, query, limit)
        dense_items = dense_future.result()
        try:
            sparse_items = sparse_future.result()
        except UpstreamServiceError:
            return dense_items[:limit]
    with _search_span("rag.search.fusion", {"dense_count": len(dense_items), "sparse_count": len(sparse_items), "rrf_k": rrf_k}) as span:
        results = _merge_rrf(dense_items, sparse_items, rrf_k)[:limit]
        span.set_attribute("result_count", len(results))
        return results


def _merge_rrf(dense_items: list[dict], sparse_items: list[dict], rrf_k: int) -> list[dict]:
    merged: dict[object, dict] = {}
    for items in (dense_items, sparse_items):
        for rank, item in enumerate(items, start=1):
            key = _dedupe_key(item)
            if key not in merged:
                result = dict(item)
                result["_score"] = 0.0
                merged[key] = result
            merged[key]["_score"] = float(merged[key].get("_score", 0.0)) + 1.0 / (rrf_k + rank)
    results = list(merged.values())
    results.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
    return results


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dedupe_key(item: dict):
    return item.get("id") or (item.get("content"), tuple(sorted((item.get("metadata") or {}).items())))


def _public_item(item: dict) -> dict:
    result = {key: value for key, value in item.items() if not key.startswith("_")}
    if "_score" in item:
        result["score"] = float(item["_score"])
    return result
