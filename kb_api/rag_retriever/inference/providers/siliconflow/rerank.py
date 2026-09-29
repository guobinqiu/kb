from __future__ import annotations

import time

import httpx

from kb_api.rag_retriever.common.retry import retry_call
from kb_api.rag_retriever.common.upstream import retryable_response, upstream_error

from .base import SiliconFlowModel
from .schemas import _RerankResponse


class SiliconFlowRerankClient(SiliconFlowModel):
    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        return retry_call(
            lambda: self._rerank_once(query, items, top_k),
            self.retry,
            operation_name="inference.siliconflow.rerank",
        )

    def _rerank_once(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        started = time.perf_counter()
        response = None
        try:
            response = self._client.post(
                f"{self.base_url}/rerank",
                json={
                    "query": query,
                    "documents": [item["content"] for item in items],
                    "top_n": top_k,
                    "model": self.model,
                    "return_documents": False,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            error = upstream_error("inference", exc, retryable=retryable_response(response))
            self._log_call("rerank", started, response, error, top_k=top_k)
            raise error from exc
        try:
            rows = _RerankResponse.model_validate(response.json(), strict=True).results
            indices = [row.index for row in rows]
            if len(rows) > min(top_k, len(items)) or len(set(indices)) != len(indices) or any(index >= len(items) for index in indices):
                raise ValueError("Invalid rerank indices")
            results = []
            for row in rows:
                result = dict(items[row.index])
                result["_score"] = row.relevance_score
                results.append(result)
        except (KeyError, TypeError, ValueError) as exc:
            error = upstream_error("inference", exc, retryable=retryable_response(response))
            self._log_call("rerank", started, response, error, top_k=top_k)
            raise error from exc
        self._log_call("rerank", started, response, top_k=top_k)
        return results
