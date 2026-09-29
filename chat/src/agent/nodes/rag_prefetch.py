"""agent/nodes/rag_prefetch.py: Pre-fetch RAG results before LLM.

Calls RagClient.search() with the user's last message, formats results,
and stores them in state["rag_context"] for the llm node to inject.
"""

from __future__ import annotations

import asyncio
from typing import Any

from chat.src.agent.stream import safe_get_writer
from chat.src.api import auth
from chat.src.rag import client as rag_client
from chat.src.rag.schemas import SearchRequest


class RagSearchError(RuntimeError):
    service = "rag"


async def rag_prefetch_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pre-fetch RAG results for the current user question.

    Reads the last HumanMessage, calls RagClient.search(),
    and returns rag_context string for llm node.
    """
    messages = state.get("messages") or []
    if not messages:
        return {"rag_context": ""}

    # Find the last HumanMessage
    query = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            query = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not query.strip():
        return {"rag_context": ""}

    credential = auth.get_current_credential()
    if credential is None:
        return {"rag_context": ""}

    workspace_ids = state.get("workspace_ids") or []
    if not workspace_ids:
        return {"rag_context": "[RAG 检索完成，未找到可访问的工作区]"}

    client = rag_client.get_rag_client()

    async def search_workspace(workspace_id: str):
        result = await client.search(
            SearchRequest(query=query, workspace_ids=[workspace_id], top_k=3),
            authorization=auth.get_current_authorization(),
            app_id=credential.app_id,
        )
        if not result.success:
            raise RagSearchError(f"{workspace_id}: {result.error}")
        return result

    try:
        results = await asyncio.gather(*(search_workspace(workspace_id) for workspace_id in workspace_ids))
    except RagSearchError:
        raise
    except Exception as exc:
        raise RagSearchError(str(exc)) from exc

    context_parts = []
    document_count = 0
    for workspace_id, result in zip(workspace_ids, results):
        if not result.documents:
            continue
        context_parts.append(f"[工作区 {workspace_id}]")
        for doc in result.documents:
            filename = (getattr(doc, "metadata", {}) or {}).get("filename")
            context_parts.append(f"文件：{filename}\n{doc.content}" if filename else doc.content)
            document_count += 1

    if not document_count:
        return {"rag_context": "[RAG 检索完成，未找到相关文档]"}

    writer = safe_get_writer()
    if writer is not None:
        try:
            writer({
                "type": "rag_context",
                "count": document_count,
                "elapsed_ms": max(result.elapsed_ms for result in results),
            })
        except Exception:
            pass
    return {"rag_context": "\n\n".join(context_parts)}
