from __future__ import annotations

import httpx

from kb_api.rag_indexer.parser.common.contracts import ErrorResponse
from kb_api.rag_indexer.parser.common.tracing import get_trace_id


class UpstreamServiceError(RuntimeError):
    def __init__(self, *, service: str, error: str | None, retryable: bool, status_code: int, trace_id: str | None = None):
        super().__init__(error)
        self.service = service
        self.error = error
        self.retryable = retryable
        self.status_code = status_code
        self.trace_id = trace_id or get_trace_id()

    def detail(self) -> dict:
        return ErrorResponse(error=self.error, service=self.service, retryable=self.retryable, traceId=self.trace_id).model_dump()


def _external_error(detail: object) -> str | None:
    if not isinstance(detail, dict):
        return None
    error = detail.get("error")
    message = error.get("message") if isinstance(error, dict) else error
    if not isinstance(message, str):
        message = detail.get("message")
    return message if isinstance(message, str) else None


def upstream_error(service: str, exc: Exception, *, retryable: bool = False) -> UpstreamServiceError:
    if isinstance(exc, httpx.TimeoutException):
        return UpstreamServiceError(service=service, error=str(exc) or None, retryable=True, status_code=504)
    if isinstance(exc, httpx.NetworkError):
        return UpstreamServiceError(service=service, error=str(exc) or None, retryable=True, status_code=503)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            detail = exc.response.json()
        except ValueError:
            detail = None
        error = _external_error(detail)
        return UpstreamServiceError(
            service=service, error=error if error is not None else exc.response.text,
            retryable=retryable if 500 <= status < 600 else False,
            status_code=502,
        )
    return UpstreamServiceError(service=service, error=str(exc) or None, retryable=False, status_code=502)


def internal_error(service: str, exc: Exception) -> UpstreamServiceError:
    if not isinstance(exc, httpx.HTTPStatusError):
        return upstream_error(service, exc)
    try:
        detail = ErrorResponse.model_validate_json(exc.response.content)
    except ValueError:
        return UpstreamServiceError(service=service, error=exc.response.text, retryable=False, status_code=502)
    return UpstreamServiceError(
        service=detail.service or service, error=detail.error, retryable=detail.retryable,
        status_code=exc.response.status_code, trace_id=detail.traceId,
    )
