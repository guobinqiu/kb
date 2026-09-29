from __future__ import annotations

import time
from threading import Lock

import httpx

from kb_api.rag_indexer.common.config import RetryConfig
from kb_api.rag_indexer.common.retry import retry_call
from kb_api.rag_indexer.common.upstream import retryable_response, upstream_error

from .base import TeiModel
from .schemas import _EmbeddingResponse


class TeiDenseClient(TeiModel):
    def __init__(self, base_url: str, model: str, timeout: float = 60.0, http_client: httpx.Client | None = None, *, dimensions: int | None = None, retry: RetryConfig | None = None, batch_size: int = 32):
        super().__init__(base_url, model, timeout, http_client, retry)
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._vector_size = dimensions
        self._dimension_lock = Lock()

    @property
    def vector_size(self) -> int:
        with self._dimension_lock:
            if self._vector_size is None:
                self._vector_size = len(self.embed_query("dimension probe"))
            return self._vector_size

    def ping(self) -> bool:
        return self.ready

    def embed_query(self, text: str) -> list[float]:
        return self._create_dense_embeddings(text)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._create_dense_embeddings(texts[start:start + self.batch_size]))
        return vectors

    def _create_dense_embeddings(self, value: str | list[str]) -> list[list[float]]:
        return retry_call(
            lambda: self._create_dense_embeddings_once(value),
            self.retry,
            operation_name="inference.tei.dense",
            enforce_deadline=False,
            logger_name="inference.retry",
        )

    def _create_dense_embeddings_once(self, value: str | list[str]) -> list[list[float]]:
        payload = {"input": value, "model": self.model, "encoding_format": "float"}
        started = time.perf_counter()
        response = None
        try:
            response = self._client.post(f"{self.base_url}/v1/embeddings", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            error = upstream_error("inference", exc, retryable=retryable_response(response))
            self._log_call("dense", started, response, error, dimensions=self.dimensions)
            raise error from exc
        try:
            rows = sorted(_EmbeddingResponse.model_validate(response.json(), strict=True).data, key=lambda item: item.index)
            count = 1 if isinstance(value, str) else len(value)
            if [row.index for row in rows] != list(range(count)):
                raise ValueError("Invalid embedding count or indices")
            vectors = [row.embedding for row in rows]
            dimensions = self.dimensions if self.dimensions is not None else (len(vectors[0]) if vectors else None)
            if any(len(vector) != dimensions for vector in vectors):
                raise ValueError("Invalid embedding dimensions")
        except (TypeError, ValueError) as exc:
            error = upstream_error("inference", exc, retryable=retryable_response(response))
            self._log_call("dense", started, response, error, dimensions=self.dimensions)
            raise error from exc
        self._log_call("dense", started, response, dimensions=self.dimensions)
        return vectors
