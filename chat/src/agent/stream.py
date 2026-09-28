"""agent/stream.py: 跨节点的流式输出工具。

集中 safe_get_writer / write_reply，避免循环依赖。
"""

from __future__ import annotations

from typing import Any


def safe_get_writer():
    """获取 LangGraph stream_writer；不可用（如 ainvoke 路径）时返回 None。

    - graph.astream(stream_mode="custom") 下：返回 writer（可写 dict）
    - graph.ainvoke 路径：get_stream_writer() 抛异常 → 返回 None
    """
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001
        return None


def write_reply(writer: Any, content: str) -> None:
    """通过 writer 推送回复给前端。writer 为 None 时静默跳过。"""
    if writer is not None and content:
        writer({"type": "token", "content": content})
