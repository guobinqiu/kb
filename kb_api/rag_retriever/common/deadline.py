import time
from contextlib import contextmanager
from contextvars import ContextVar

from kb_api.rag_retriever.common.upstream import UpstreamServiceError


_deadline: ContextVar[float | None] = ContextVar("index_deadline", default=None)


def index_timeout_error() -> UpstreamServiceError:
    return UpstreamServiceError(
        service="rag", error="Indexing deadline exceeded",
        retryable=False, status_code=504,
    )


@contextmanager
def index_deadline(seconds: float):
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def check_deadline() -> None:
    end = _deadline.get()
    if end is not None and time.monotonic() >= end:
        raise index_timeout_error()


def request_timeout(configured: float) -> float:
    end = _deadline.get()
    if end is None:
        return configured
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise index_timeout_error()
    return min(configured, remaining)
