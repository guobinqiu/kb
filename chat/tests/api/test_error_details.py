import json

import httpx
import pytest
from fastapi import Request
from openai import APIConnectionError, APIStatusError, RateLimitError

from chat.src import main


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("handler,error,status", [
    (main.api_status_handler, APIStatusError("model unavailable: details", response=httpx.Response(500, request=httpx.Request("POST", "https://model.test")), body=None), 502),
    (main.rate_limit_handler, RateLimitError("quota exceeded: details", response=httpx.Response(429, request=httpx.Request("POST", "https://model.test")), body=None), 429),
    (main.connection_handler, APIConnectionError(message="connection refused: details", request=httpx.Request("POST", "https://model.test")), 503),
    (main.general_handler, RuntimeError("database query failed: details"), 500),
])
async def test_exception_handlers_return_original_error(handler, error, status):
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/llm/chat/stream", "headers": [], "app": main.app, "state": {"trace_id": "a" * 32}})
    response = await handler(request, error)
    assert response.status_code == status
    assert json.loads(response.body)["error"] == str(error)
    assert json.loads(response.body)["service"] == "chat"
