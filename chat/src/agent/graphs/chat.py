"""agent/graphs/chat.py: 主对话图。

结构：
    query_rewrite → rag_prefetch → llm → END

每轮对话先预检索 RAG，再由 LLM 基于检索结果生成回答。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from chat.src.agent.nodes.llm import llm_node
from chat.src.agent.nodes.query_rewrite import query_rewrite_node
from chat.src.agent.nodes.rag_prefetch import rag_prefetch_node
from chat.src.agent.states.base import AgentState


def build_chat_graph(checkpointer):
    """构造 chat 主图。

    Args:
        checkpointer: LangGraph checkpointer。

    返回编译后的 StateGraph。
    """
    builder = StateGraph(AgentState)

    # 节点：query_rewrite（补全多轮问题）/ rag_prefetch（预检索 RAG）/ llm（生成回答）
    builder.add_node("query_rewrite", query_rewrite_node)
    builder.add_node("rag_prefetch", rag_prefetch_node)
    builder.add_node("llm", llm_node)

    # 入口
    builder.set_entry_point("query_rewrite")

    # query_rewrite → rag_prefetch → llm
    builder.add_edge("query_rewrite", "rag_prefetch")
    builder.add_edge("rag_prefetch", "llm")

    # llm → END
    builder.add_edge("llm", END)

    return builder.compile(checkpointer=checkpointer)
