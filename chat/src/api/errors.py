import logging

from fastapi.responses import JSONResponse

from chat.src.infra.tracing import get_trace_id


logger = logging.getLogger("chat.errors")


async def unhandled_exception_handler(request, exc):
    trace_id = getattr(request.state, "trace_id", None) or get_trace_id()
    logger.error(
        "Unhandled service error",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"trace_id": trace_id, "method": request.method, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": str(exc) or repr(exc),
            "service": "chat",
            "retryable": False,
            "traceId": trace_id,
        },
        headers={"X-Trace-Id": trace_id},
    )
