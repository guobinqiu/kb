import ast
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi import FastAPI

from chat.src import main
from chat.src.api.middleware import limiter
from chat.src.api.middleware.trace_timeout import add_trace_id_and_timeout
from chat.src.api.routes import chat
from chat.src.infra import tracing


def _user_token() -> str:
    payload = {
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        "sub": "user-1",
    }
    return jwt.encode(payload, "test-secret-at-least-32-bytes-long", algorithm="HS256")


def test_no_tracking_imports():
    for path in (Path(__file__).resolve().parents[2] / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            assert not any(module.split(".")[0] in {"opentelemetry", "langsmith"} for module in modules), path


@pytest.mark.parametrize("traceparent", [None, "invalid", "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"])
async def test_error_and_sse_request_ids(monkeypatch, traceparent):

    monkeypatch.setattr(limiter, "enabled", False)
    app = FastAPI(exception_handlers=main.app.exception_handlers)
    app.middleware("http")(add_trace_id_and_timeout)
    observed = []

    @app.get("/boom")
    async def boom():
        observed.append(tracing.get_trace_id())
        raise RuntimeError("failure")

    @app.get("/number")
    async def number(value: int):
        return value

    class Graph:
        async def astream(self, *args, **kwargs):
            observed.append(tracing.get_trace_id())
            yield "custom", {"type": "token", "content": "first"}
            await asyncio.sleep(0)
            observed.append(tracing.get_trace_id())
            assert tracing.get_thread_id() == "thread"
            raise RuntimeError("stream failure")

    app.include_router(chat.router)
    app.dependency_overrides[chat._chat_graph] = lambda: Graph()
    headers = {"traceparent": traceparent} if traceparent else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        responses = await asyncio.gather(*[
            client.get(path, headers=headers) for path in ("/boom", "/number?value=no", "/missing")
        ])
        assert [response.status_code for response in responses] == [500, 422, 404]
        for response in responses:
            assert response.json()["traceId"] == response.headers["x-trace-id"]
        assert observed[0] == responses[0].headers["x-trace-id"]
        sse = await client.post("/api/v1/llm/chat/stream", json={
            "message": "question", "thread_id": "thread", "workspace_ids": ["ws"],
        }, headers={
            **headers,
            "Authorization": f"Bearer {_user_token()}",
            "X-App-Id": "app",
        })
        events = [json.loads(line[6:]) for line in sse.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "error"
        assert events[-1]["traceId"] == events[-1]["trace_id"] == sse.headers["x-trace-id"]
        assert observed[-2:] == [sse.headers["x-trace-id"]] * 2
        ids = [response.headers["x-trace-id"] for response in [*responses, sse]]
        for trace_id in ids:
            assert len(trace_id) == 32 and int(trace_id, 16) != 0
        assert len(set(ids)) == len(ids)
    assert tracing.get_trace_id() == "-"
