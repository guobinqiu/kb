from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from chat.src.agent.registry import get_checkpointer, get_graph
from chat.src.api.middleware import limiter
from chat.src.api.requests import ThreadId
from chat.src.config import settings

router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadSummary(BaseModel):
    thread_id: str
    message_count: int
    created_at: str | None = None
    updated_at: str | None = None


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]
    total: int


@router.get("", response_model=ThreadListResponse)
@limiter.limit(settings.rate_limit_history)
async def list_threads(request: Request):
    """列出所有对话线程，按最后更新时间倒序。"""
    checkpointer = get_checkpointer()
    threads: dict[str, ThreadSummary] = {}
    async for checkpoint in checkpointer.alist(None, limit=1000):
        thread_id = _checkpoint_thread_id(checkpoint)
        if not thread_id or thread_id in threads:
            continue
        updated_at = _checkpoint_updated_at(checkpoint)
        threads[thread_id] = ThreadSummary(
            thread_id=thread_id,
            message_count=_checkpoint_message_count(checkpoint),
            created_at=updated_at,
            updated_at=updated_at,
        )
    summaries = list(threads.values())
    return ThreadListResponse(threads=summaries, total=len(summaries))


def _checkpoint_thread_id(checkpoint) -> str | None:
    config = getattr(checkpoint, "config", None) or {}
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else None


def _checkpoint_updated_at(checkpoint) -> str | None:
    payload = getattr(checkpoint, "checkpoint", None) or {}
    value = payload.get("ts")
    return str(value) if value else None


def _checkpoint_message_count(checkpoint) -> int:
    payload = getattr(checkpoint, "checkpoint", None) or {}
    values = payload.get("channel_values") or {}
    messages = values.get("messages") or []
    return len(messages) if isinstance(messages, list) else 0


@router.delete("/{thread_id}")
@limiter.limit(settings.rate_limit_history)
async def delete_thread(request: Request, thread_id: ThreadId):
    """删除指定对话线程的所有检查点数据。"""
    checkpointer = get_checkpointer()
    delete_thread_func = getattr(checkpointer, "adelete_thread", None)
    if not callable(delete_thread_func):
        return {"deleted": False, "thread_id": thread_id}
    await delete_thread_func(thread_id)

    return {"deleted": True, "thread_id": thread_id}


def _chat_graph():
    return get_graph("chat")


@router.get("/{thread_id}/history")
@limiter.limit(settings.rate_limit_history)
async def get_history(request: Request, thread_id: ThreadId, graph=Depends(_chat_graph)):  # noqa: B008
    """获取指定对话的消息历史。

    B008：FastAPI 框架强制要求 Depends() 在参数默认位置（C 端解析依赖图）。
    """
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)

    if not state.values:
        return {"thread_id": thread_id, "messages": []}

    messages = [
        {
            "role": "user" if isinstance(msg, HumanMessage) else "ai",
            "content": msg.content,
        }
        for msg in state.values["messages"]
    ]
    return {"thread_id": thread_id, "messages": messages}
