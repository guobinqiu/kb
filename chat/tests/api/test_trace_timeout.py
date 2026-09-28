import asyncio
import json

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from chat.src.api.middleware import trace_timeout

pytestmark = pytest.mark.unit


async def test_trace_timeout_sets_trace_context_and_response_header():
    request = Request({"type": "http", "method": "GET", "path": "/health", "headers": []})

    async def next_handler(request):
        assert request.state.trace_id == trace_timeout.get_trace_id()
        return JSONResponse({"status": "ok"})

    response = await trace_timeout.add_trace_id_and_timeout(request, next_handler)

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == request.state.trace_id


async def test_trace_timeout_returns_error_response(monkeypatch):
    monkeypatch.setattr(trace_timeout.settings, "request_timeout", 0.001)
    request = Request({"type": "http", "method": "GET", "path": "/slow", "headers": []})

    async def next_handler(request):
        await asyncio.sleep(0.1)

    response = await trace_timeout.add_trace_id_and_timeout(request, next_handler)
    body = json.loads(response.body)

    assert response.status_code == 504
    assert response.headers["X-Trace-Id"] == request.state.trace_id
    assert body == {
        "error": "TimeoutError()",
        "service": "chat",
        "timeout": 0.001,
        "traceId": request.state.trace_id,
    }
