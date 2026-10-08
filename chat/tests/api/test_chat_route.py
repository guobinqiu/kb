"""Chat 路由单测（§11.1）。

覆盖：
- 直接调用 chat_stream 并迭代 StreamingResponse，返回 text/event-stream，
  收到 SSE 事件 token/done
- Cache-Control / Connection / X-Accel-Buffering 头
"""

from __future__ import annotations

import json
from hashlib import sha256

import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import APITimeoutError
from pydantic import ValidationError

from starlette.requests import Request

import chat.src.api.auth as auth_mod
from chat.src.api.auth import AppCredential, get_current_authorization
from chat.src.api.middleware import limiter
from chat.src.api.routes.chat import ChatRequest, chat_stream


pytestmark = pytest.mark.unit


class ServiceError(RuntimeError):
    def __init__(self, message: str, service: str):
        super().__init__(message)
        self.service = service


@pytest.fixture
def route_request(monkeypatch):

    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="", api_key="", user_id="user-1"),
    )
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/llm/chat/stream",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    })


# ────────────────────────── 流式 /api/v1/llm/chat/stream ──────────────────────────


def _parse_sse(raw: str) -> list:
    """解析 SSE 流 → list[dict]."""
    events: list = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    # 不可解析时记原始串
                    events.append({"_raw": payload})
    return events


async def test_chat_stream_returns_event_stream_content_type(route_request):
    """chat_stream 必须返回 text/event-stream content type。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1", workspace_ids=["ws-1"]), graph=_Graph())
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert ct.startswith("text/event-stream"), f"unexpected content-type: {ct}"


async def test_chat_stream_passes_all_workspace_ids_to_graph(route_request):
    observed = []

    class _Graph:
        async def astream(self, input_data, **kwargs):
            observed.append(input_data["workspace_ids"])
            yield ("custom", {"type": "token", "content": "ok"})

    response = await chat_stream(
        route_request,
        ChatRequest(message="policy", thread_id="t1", workspace_ids=["ws-1", "ws-2"]),
        graph=_Graph(),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert observed == [["ws-1", "ws-2"]]


async def test_chat_stream_sets_required_sse_headers(route_request):
    """SSE 响应头必须含 Cache-Control/Connection/X-Accel-Buffering。"""

    class _Graph:
        async def astream(self, *a, **kw):
            if False:
                yield ("values", {})

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1", workspace_ids=["ws-1"]), graph=_Graph())
    assert resp.status_code == 200
    headers = resp.headers
    assert "no-cache" in headers.get("Cache-Control", "").lower()
    assert headers.get("Connection", "").lower() == "keep-alive"
    assert headers.get("X-Accel-Buffering") == "no"


async def test_chat_stream_emits_token_done_events(route_request, monkeypatch):
    """SSE 序列化单测：graph 应推 token* → done 序列。"""

    written: list = []
    final_state = {"messages": [AIMessage(content="综合回复：退款 7 天")]}

    class _Graph:
        async def astream(self, input_data, config=None, stream_mode=None):
            assert input_data["messages"][0].content == "refund?"
            assert config == {"configurable": {"thread_id": sha256(b":user-1:t1").hexdigest()}}
            assert stream_mode == ["custom"]

            async def _producer():
                for chunk in ["退款", " ", "7", " 天"]:
                    yield ("custom", {"type": "token", "content": chunk})
                yield ("values", final_state)

            async for ev in _producer():
                mode, payload = ev
                if stream_mode and not (
                    mode in stream_mode
                    or (isinstance(stream_mode, list) and mode in stream_mode)
                ):
                    continue
                yield (mode, payload)
                # 记录
                if mode == "custom":
                    written.append(payload)

    route_request.scope["headers"] = [
        (b"x-user-id", b"user-1"),
    ]
    resp = await chat_stream(route_request, ChatRequest(message="refund?", thread_id="t1", workspace_ids=["ws-1"]), graph=_Graph())
    assert resp.status_code == 200
    raw = "".join([chunk async for chunk in resp.body_iterator])

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]

    assert "token" in types, f"SSE 事件中应含 token，实际 type 序列: {types}"
    assert "done" in types
    assert types[-1] == "done"
    assert events == [*written, {"type": "done"}]
    assert "".join(event["content"] for event in events if event["type"] == "token") == "退款 7 天"


async def test_chat_stream_passes_workspace_scope_in_same_app_thread(route_request, monkeypatch):

    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="acme", api_key="", user_id="user-1"),
    )
    observed = []

    class _Graph:
        async def astream(self, input_data, config=None, stream_mode=None):
            observed.append((input_data["workspace_ids"], config["configurable"]["thread_id"]))
            yield ("custom", {"type": "token", "content": "ok"})

    for workspace_id in ("workspace-a", "workspace-b"):
        response = await chat_stream(route_request, ChatRequest(message="policy", thread_id="t1", workspace_ids=[workspace_id]), graph=_Graph())
        _ = [chunk async for chunk in response.body_iterator]

    assert observed[0][0] == ["workspace-a"]
    assert observed[1][0] == ["workspace-b"]
    assert observed[0][1] == observed[1][1]


async def test_chat_stream_isolates_same_thread_for_different_users(route_request, monkeypatch):
    thread_ids = []

    class _Graph:
        async def astream(self, input_data, config=None, stream_mode=None):
            thread_ids.append(config["configurable"]["thread_id"])
            yield ("custom", {"type": "token", "content": "ok"})

    for user_id in ("user-1", "user-2"):
        monkeypatch.setattr(
            auth_mod,
            "get_current_credential",
            lambda user_id=user_id: AppCredential(app_id="acme", api_key="", user_id=user_id),
        )
        response = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1", workspace_ids=["ws-1"]), graph=_Graph())
        _ = [chunk async for chunk in response.body_iterator]

    assert thread_ids[0] != thread_ids[1]


def test_chat_request_rejects_empty_workspace_ids():

    with pytest.raises(ValidationError):
        ChatRequest(message="hi", thread_id="t1", workspace_ids=[])


async def test_chat_stream_forwards_authorization_during_graph_run(route_request):

    route_request.scope["headers"] = [
        (b"authorization", b"Bearer user-token"),
        (b"x-user-id", b"user-1"),
    ]
    observed = []

    class _Graph:
        async def astream(self, *args, **kwargs):
            observed.append(get_current_authorization())
            yield ("custom", {"type": "token", "content": "ok"})

    response = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1", workspace_ids=["ws-1"]), graph=_Graph())
    _ = [chunk async for chunk in response.body_iterator]

    assert observed == ["Bearer user-token"]
    assert get_current_authorization() is None


@pytest.mark.parametrize("error,service", [
    (RuntimeError("upstream broken"), "chat"),
    (APITimeoutError(request=httpx.Request("POST", "https://model.test")), "chat"),
    (ServiceError("search failed", "rag"), "rag"),
])
async def test_chat_stream_handles_error_emits_error_event(route_request, monkeypatch, error, service):
    """graph 抛异常时，SSE 应推 error 事件而不是返回 5xx。"""

    class _FailGraph:
        async def astream(self, *a, **kw):
            raise error
            yield  # for type checker

    resp = await chat_stream(route_request, ChatRequest(message="hi", thread_id="t1", workspace_ids=["ws-1"]), graph=_FailGraph())
    assert resp.status_code == 200  # SSE 业务错误保持 200
    raw = "".join([chunk async for chunk in resp.body_iterator])

    events = _parse_sse(raw)
    types = [e.get("type") for e in events]
    assert "error" in types, f"应推 error 事件，实际: {types}"
    err = next(e for e in events if e.get("type") == "error")
    assert "message" in err or "trace_id" in err
    assert err["message"] == str(error)
    assert err["service"] == service
    assert types == ["error"]



def test_chat_route_module_path():
    """chat 路由必须位于 api.routes.chat 且包含 /api/v1/llm/chat/stream 端点。"""
    try:
        from chat.src.api.routes.chat import router  # type: ignore
    except ImportError as exc:
        pytest.fail(f"api.routes.chat.router 缺失: {exc}")
    paths = sorted({getattr(r, "path", "") for r in router.routes})
    assert "/api/v1/llm/chat/stream" in paths, (
        f"router 中必须含 /api/v1/llm/chat/stream（架构 §6.1 SSE 端点要求），当前: {paths}"
    )
