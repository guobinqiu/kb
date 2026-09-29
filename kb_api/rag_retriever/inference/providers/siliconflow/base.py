from __future__ import annotations

import logging
import time

import httpx

from kb_api.rag_retriever.common.config import RetryConfig
from kb_api.api.telemetry import get_trace_id
from kb_api.rag_retriever.common.upstream import UpstreamServiceError


logger = logging.getLogger("kb_api.rag_retriever.inference.providers.siliconflow")


class SiliconFlowModel:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 60.0, api_key: str | None = None, http_client: httpx.Client | None = None, retry: RetryConfig | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self.retry = retry or RetryConfig()
        self.ready = True

    def close(self) -> None:
        self._client.close()
        self.ready = False

    def _log_call(self, operation: str, started: float, response: httpx.Response | None, error: UpstreamServiceError | None = None, **context) -> None:
        name = "dense" if operation == "embedding" else "rerank"
        logger.log(
            logging.ERROR if error else logging.INFO,
            f"SiliconFlow {name} request {'failed' if error else 'completed'}",
            exc_info=error is not None,
            extra={
                "event": f"siliconflow_{name}_{'error' if error else 'success'}",
                "service": "inference",
                "operation": operation,
                "model": self.model,
                "trace_id": get_trace_id(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "status_code": response.status_code if response is not None else None,
                "provider_request_id": response.headers.get("x-request-id") if response is not None else None,
                "retryable": error.retryable if error else None,
                "error": error.error if error else None,
                "upstream_response": response.text if error and response is not None else None,
                **context,
            },
        )
