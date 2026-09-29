from __future__ import annotations

import logging
import os
from pathlib import Path

from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.common.config import SearchConfig, load_search_config, load_vector_config
from kb_api.rag_retriever.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_retriever.clients.vector.qdrant import QdrantVectorClient
from kb_api.rag_retriever.core.scope import validate_app_id
from kb_api.rag_retriever.core.search import SearchPlan, _SearchExecutor
from kb_api.rag_retriever.inference.config_loader import load_inference_config
from kb_api.rag_retriever.inference.service import load_inference_components
from kb_api.rag_retriever.schemas import SearchRequest


logger = logging.getLogger(__name__)


class RetrieverRequestError(ValueError):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Retriever:
    def __init__(self, search_config: SearchConfig, vector, inference):
        self.search_config = search_config
        self.vector = vector
        self.inference = inference

    def close(self) -> None:
        for component in (self.vector, self.inference):
            component.close()

    def search(self, request: SearchRequest) -> dict:
        validate_app_id(request.app_id)
        rerank = self.search_config.rerank if request.rerank is None else request.rerank
        plan = SearchPlan(
            request.query,
            app_id=request.app_id,
            mode=request.mode or self.search_config.mode,
            top_k=request.top_k or self.search_config.top_k,
            rerank_fetch_k=request.rerank_fetch_k or self.search_config.rerank_fetch_k,
            rerank=rerank,
            rrf_k=request.rrf_k or self.search_config.rrf_k,
            file_ids=request.file_ids,
            workspace_ids=request.workspace_ids,
        )
        sparse_ready = self.vector.supports_sparse_vector()
        if plan.mode == "sparse" and not sparse_ready:
            raise RetrieverRequestError(status_code=400, detail="sparse search is not configured")
        if plan.mode == "hybrid" and not sparse_ready:
            plan = _replace_mode(plan, "dense")
        rerank_client = self.inference.rerank
        if plan.rerank and rerank_client is None:
            plan = _disable_rerank(plan)
        if not self.vector.app_collection_exists(request.app_id):
            return _response(plan, [], 0.0)
        try:
            with self.vector.app_scope(request.app_id):
                executor = _SearchExecutor(plan, vector=self.vector, rerank=rerank_client)
                results = executor.execute()
        except (RetrieverRequestError, UpstreamServiceError):
            raise
        except Exception as exc:
            logger.exception("Search failed")
            raise UpstreamServiceError(service="kb_api.rag_retriever", error=str(exc), retryable=False, status_code=500) from exc
        return _response(plan, results, executor.elapsed_ms)

def _response(plan: SearchPlan, results: list[dict], elapsed_ms: float) -> dict:
    return {
        "results": results,
        "mode": plan.mode,
        "rerank": plan.rerank,
        "rerank_fetch_k": plan.rerank_fetch_k if plan.rerank else None,
        "elapsed_ms": elapsed_ms,
    }


def _replace_mode(plan: SearchPlan, mode: str) -> SearchPlan:
    return SearchPlan(
        plan.query, app_id=plan.app_id, mode=mode, top_k=plan.top_k,
        rerank_fetch_k=plan.rerank_fetch_k, rerank=plan.rerank,
        rrf_k=plan.rrf_k, file_ids=plan.file_ids, workspace_ids=plan.workspace_ids,
    )


def _disable_rerank(plan: SearchPlan) -> SearchPlan:
    return SearchPlan(
        plan.query, app_id=plan.app_id, mode=plan.mode, top_k=plan.top_k,
        rerank_fetch_k=plan.rerank_fetch_k, rerank=False,
        rrf_k=plan.rrf_k, file_ids=plan.file_ids, workspace_ids=plan.workspace_ids,
    )


def load_retriever() -> Retriever:
    config_path = Path(os.getenv("KB_CONFIG_FILE", Path(__file__).resolve().parents[1] / "config/rag.yaml"))
    vector_config = load_vector_config(config_path)
    inference = load_inference_components(load_inference_config(config_path))
    if vector_config.provider == "qdrant":
        vector = QdrantVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            url=vector_config.base_url,
            timeout=vector_config.timeout,
            query_timeout=vector_config.query_timeout,
            init_timeout=vector_config.init_timeout,
            drop_timeout=vector_config.drop_timeout,
            quantization=vector_config.quantization,
            api_key=vector_config.api_key,
            retry=vector_config.retry,
        )
    elif vector_config.provider == "milvus":
        vector = MilvusVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            uri=vector_config.base_url,
            timeout=vector_config.timeout,
            query_timeout=vector_config.query_timeout,
            init_timeout=vector_config.init_timeout,
            drop_timeout=vector_config.drop_timeout,
            token=vector_config.token,
            retry=vector_config.retry,
        )
    else:
        inference.close()
        raise ValueError(f"unsupported vector: {vector_config.provider}")

    return Retriever(load_search_config(config_path), vector, inference)
