import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse

from chat.src.config import settings
from chat.src.infra.tracing import (
    get_trace_id,
    reset_request_trace,
    start_request_trace,
)


async def add_trace_id_and_timeout(request: Request, call_next):
    token = start_request_trace(request.headers)
    trace_id = get_trace_id()
    request.state.trace_id = trace_id

    try:
        response = await asyncio.wait_for(
            call_next(request),
            timeout=settings.request_timeout,
        )
        response.headers["X-Trace-Id"] = trace_id
        return response
    except TimeoutError as exc:
        return JSONResponse(
            status_code=504,
            content={
                "error": str(exc) or repr(exc),
                "service": "chat",
                "timeout": settings.request_timeout,
                "traceId": trace_id,
            },
            headers={"X-Trace-Id": trace_id},
        )
    finally:
        reset_request_trace(token)


__all__ = ["add_trace_id_and_timeout", "get_trace_id"]
