"""Chat Graph 组件测试（预检索架构）。

覆盖：
- 图装配最小 happy path
- rag_prefetch → llm → END 链路
- rag_context 正确注入 LLM 消息
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

import chat.src.agent.nodes.llm as llm_mod
import chat.src.api.auth as auth_mod
from chat.src.agent.graphs.chat import build_chat_graph
from chat.src.agent.nodes.rag_prefetch import rag_prefetch_node
from chat.src.api.auth import AppCredential


@pytest.mark.asyncio
@pytest.mark.unit
async def test_build_chat_graph_builds_successfully():
    """build_chat_graph 必须接受 checkpointer 参数并返回编译图。"""


    graph = build_chat_graph(MemorySaver())
    assert graph is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_chat_graph_prefetch_then_llm_ends(monkeypatch):
    """组件协作：rag_prefetch → llm → END，外部客户端使用 mock。"""

    # Mock RagClient
    class _Doc:
        def __init__(self, content):
            self.id = "mock-1"
            self.content = content

    class _Res:
        success = True
        status_code = 200
        documents = [_Doc("退款政策：7天内可退")]
        elapsed_ms = 5.0
        raw = {}
        error = ""

    class _FakeClient:
        async def aclose(self): pass
        async def search(self, req, **kwargs): return _Res()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _FakeClient())


    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", api_key="test-api-key"),
    )

    # Mock LLM
    class _FakeLLM:
        async def astream(self, messages):
            # Verify rag_context was injected
            assert any("参考资料" in str(m.content) for m in messages if hasattr(m, "content"))
            yield AIMessageChunk(content="根据政策，7天内可退款")

    # Patch get_llm
    monkeypatch.setattr(llm_mod, "get_llm", lambda: _FakeLLM())

    graph = build_chat_graph(MemorySaver())

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="退款政策是什么？")], "workspace_id": "workspace-1"},
        config={"configurable": {"thread_id": "t1"}},
    )

    msgs = result["messages"]
    assert len(msgs) >= 2
    assert isinstance(msgs[0], HumanMessage)
    assert isinstance(msgs[-1], AIMessage)
    assert msgs[-1].content == "根据政策，7天内可退款"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rag_prefetch_empty_on_no_messages(monkeypatch):
    """空消息时 rag_prefetch 返回空 rag_context。"""
    result = await rag_prefetch_node({"messages": []})
    assert result["rag_context"] == ""


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rag_prefetch_injects_context(monkeypatch):
    """rag_prefetch 正确调用 client.search 并格式化结果。"""


    class _Doc:
        def __init__(self, content):
            self.id = "d1"
            self.content = content

    class _Res:
        success = True
        status_code = 200
        documents = [_Doc("退款7天")]
        elapsed_ms = 3.0
        raw = {}
        error = ""

    class _C:
        async def aclose(self): pass
        async def search(self, req, **kwargs): return _Res()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _C())


    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", api_key="test-api-key"),
    )

    state = {"messages": [HumanMessage(content="退款怎么退？")], "workspace_ids": ["workspace-1"]}
    result = await rag_prefetch_node(state)
    assert "退款7天" in result["rag_context"]
