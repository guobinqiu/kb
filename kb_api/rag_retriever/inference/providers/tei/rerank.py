from __future__ import annotations

import time

import httpx

from kb_api.rag_retriever.inference.common.retry import retry_call
from kb_api.rag_retriever.common.upstream import upstream_error

from .base import TeiModel
from .retryable import _retryable_response
from .schemas import _RerankRowsAdapter


class TeiRerankClient(TeiModel):
    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        return retry_call(
            lambda: self._rerank_once(query, items, top_k),
            self.retry,
            operation_name="inference.tei.rerank",
        )

    def _rerank_once(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        started = time.perf_counter()
        response = None
        try:
            response = self._client.post(
                f"{self.base_url}/rerank",
                json={
                    "query": query,
                    "texts": [item["content"] for item in items],
                    "raw_scores": False,
                    "return_text": False,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            error = upstream_error("inference", exc, retryable=_retryable_response(response))
            self._log_call("rerank", started, response, error, top_k=top_k)
            raise error from exc
        try:
            rows = _RerankRowsAdapter.validate_python(response.json(), strict=True)
            indices = [row.index for row in rows]
            if len(rows) > len(items) or len(set(indices)) != len(indices) or any(index >= len(items) for index in indices):
                raise ValueError("Invalid rerank indices")
            results = []
            for row in rows[:top_k]:
                result = dict(items[row.index])
                result["_score"] = row.score
                results.append(result)
        except (TypeError, ValueError) as exc:
            error = upstream_error("inference", exc, retryable=_retryable_response(response))
            self._log_call("rerank", started, response, error, top_k=top_k)
            raise error from exc
        self._log_call("rerank", started, response, top_k=top_k)
        return results
