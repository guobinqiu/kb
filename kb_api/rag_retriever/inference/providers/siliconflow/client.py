from __future__ import annotations

import httpx

from kb_api.rag_retriever.common.config import RetryConfig

from .dense import SiliconFlowDenseClient
from .rerank import SiliconFlowRerankClient


class SiliconFlowInferenceClient:
    def __init__(
        self,
        base_url: str = "https://api.siliconflow.cn/v1",
        *,
        dense_model: str = "BAAI/bge-m3",
        rerank_model: str = "BAAI/bge-reranker-v2-m3",
        dimensions: int | None = None,
        dense_timeout: float = 60.0,
        rerank_timeout: float | None = None,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        retry: RetryConfig | None = None,
    ):
        self.dense = SiliconFlowDenseClient(
            base_url, model=dense_model, timeout=dense_timeout, api_key=api_key, http_client=http_client,
            dimensions=dimensions, retry=retry,
        )
        self.sparse = None
        self.rerank = SiliconFlowRerankClient(
            base_url, model=rerank_model, timeout=rerank_timeout if rerank_timeout is not None else dense_timeout, api_key=api_key, http_client=http_client, retry=retry,
        ) if rerank_model else None
        self.ready = True

    def close(self) -> None:
        if self.rerank is not None:
            self.rerank.close()
        self.dense.close()
        self.ready = False

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        """Report local readiness without a remote or billable request."""
        return self.ready and self.dense.ping()
