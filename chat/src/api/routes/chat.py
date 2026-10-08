"""api/routes/chat.py: POST /api/v1/llm/chat/stream（SSE）。"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from hashlib import sha256

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import Field

from chat.src.agent.registry import get_graph
from chat.src.api import auth
from chat.src.api.middleware import limiter
from chat.src.api.requests import AgentRequest
from chat.src.config import settings
from chat.src.infra.tracing import get_trace_id, set_thread_id

router = APIRouter()


async def _chat_graph():
    """解析 chat graph 依赖。

    生产：`get_graph("chat")` 返回 graph 对象（同步）。
    测试：`monkeypatch` 把 `get_graph` 改成 async，返回 coroutine。
    为同时兼容两种场景，对返回结果做 `isawaitable` 检查。
    """
    g = get_graph("chat")
    if inspect.isawaitable(g):
        g = await g
    return g


class ChatRequest(AgentRequest):
    workspace_ids: list[str] = Field(min_length=1, max_length=1000)


def _sse(payload: dict) -> str:
    """构造 SSE 单条事件（data: <json>\\n\\n）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ───────────────────── /api/v1/llm/chat/stream ─────────────────────


@router.post("/api/v1/llm/chat/stream", dependencies=[Depends(auth.require_user_principal)])
@limiter.limit(settings.rate_limit_chat)
async def chat_stream(request: Request, req: ChatRequest, graph=Depends(_chat_graph)):  # noqa: B008
    """SSE 流式。

    B008：FastAPI 框架强制要求 Depends() 在参数默认位置（C 端解析依赖图）。
    """
    set_thread_id(req.thread_id)

    credential = auth.get_current_credential()
    scope = (
        f"{credential.app_id if credential else ''}:"
        f"{credential.user_id if credential else ''}:"
        f"{req.thread_id}"
    )
    thread_id = sha256(scope.encode()).hexdigest()
    config = {"configurable": {"thread_id": thread_id}}
    input_data = {
        "messages": [HumanMessage(content=req.message)],
        "workspace_ids": req.workspace_ids,
    }

    async def event_generator() -> AsyncIterator[str]:
        token = auth.set_current_authorization(request.headers.get("Authorization"))
        try:
            async for mode, payload in graph.astream(
                input_data,
                config=config,
                stream_mode=["custom"],
            ):
                if mode == "custom":
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") == "token":
                        content = payload.get("content") or ""
                        if content:
                            yield _sse(payload)
            yield _sse({"type": "done"})
        except Exception as e:
            yield _sse({
                "type": "error",
                "message": str(e),
                "service": getattr(e, "service", None) or "chat",
                "trace_id": get_trace_id(),
                "traceId": get_trace_id(),
            })
        finally:
            auth.reset_current_authorization(token)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
