import json
import logging

from fastapi.responses import JSONResponse

from kb_api.rag_indexer.common.tracing import get_trace_id
from kb_api.rag_indexer.common.upstream import UpstreamServiceError


logger = logging.getLogger("brain.errors")


async def unhandled_exception_handler(request, exc):
    trace_id = getattr(request.state, "trace_id", None) or get_trace_id()
    logger.error("Unhandled service error", exc_info=(type(exc), exc, exc.__traceback__), extra={
        "trace_id": trace_id, "method": request.method, "path": request.url.path,
    })
    detail = {"success": False, "error": str(exc) or repr(exc), "service": getattr(request.app.state, "service_name", request.app.title), "retryable": False, "traceId": trace_id}
    if "file_id" in request.path_params:
        detail["file_id"] = request.path_params["file_id"]
    headers = {}
    traceparent = getattr(request.state, "traceparent", None)
    if traceparent:
        headers["traceparent"] = traceparent
    return JSONResponse(status_code=500, content=detail, headers=headers)


async def upstream_exception_handler(request, exc):
    logger.error("Service request failed", exc_info=(type(exc), exc, exc.__traceback__), extra={
        "service": exc.service, "trace_id": get_trace_id(), "retryable": exc.retryable,
    })
    return JSONResponse(status_code=exc.status_code, content=exc.detail())


async def http_exception_handler(request, exc):
    error = UpstreamServiceError(
        service=getattr(request.app.state, "service_name", request.app.title), error=exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail),
        retryable=exc.status_code == 503, status_code=exc.status_code,
    )
    if request.url.path == "/ready":
        return JSONResponse(status_code=error.status_code, content=error.detail())
    return await upstream_exception_handler(request, error)


async def validation_exception_handler(request, exc):
    error = UpstreamServiceError(service=getattr(request.app.state, "service_name", request.app.title), error=str(exc), retryable=False, status_code=422)
    return await upstream_exception_handler(request, error)
