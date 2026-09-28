from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from kb_api.rag_indexer.inference.common.config import RetryConfig
from kb_api.rag_indexer.inference.common.tracing import get_trace_id
from kb_api.rag_indexer.inference.common.upstream import UpstreamServiceError


T = TypeVar("T")
logger = logging.getLogger("inference.retry")


def retry_call(
    operation: Callable[[], T],
    config: RetryConfig,
    *,
    should_retry: Callable[[Exception], bool] | None = None,
    operation_name: str = "operation",
) -> T:
    attempts = max(1, config.max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            retryable = _is_retryable(exc, should_retry)
            if attempt >= attempts or not retryable:
                raise
            logger.warning(
                "Retryable operation failed; retrying",
                extra={
                    "event": "retry_attempt",
                    "operation": operation_name,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "trace_id": get_trace_id(),
                    "error_type": type(exc).__name__,
                },
            )
            if config.interval_seconds:
                time.sleep(config.interval_seconds)
    raise RuntimeError("retry attempts exhausted")


def _is_retryable(exc: Exception, should_retry: Callable[[Exception], bool] | None) -> bool:
    if isinstance(exc, UpstreamServiceError):
        return exc.retryable
    return bool(should_retry and should_retry(exc))
