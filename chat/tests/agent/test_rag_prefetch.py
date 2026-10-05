"""RAG 预检索节点单测。

覆盖：
- rag_prefetch_node 正确调用 client.search
- 检索失败时返回错误
- 无 HumanMessage 返回空 rag_context
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import chat.src.api.auth as auth_mod
import chat.src.agent.nodes.rag_prefetch as prefetch_mod
from chat.src.agent.nodes.rag_prefetch import rag_prefetch_node
from chat.src.api.auth import AppCredential
from chat.src.rag.schemas import Document


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_rag_prefetch_calls_client_with_query(monkeypatch):
    """rag_prefetch_node 用最后一条 HumanMessage 的内容调 client.search。"""


    captured = {}

    class _C:
        async def aclose(self): pass
        async def search(self, req, **kwargs):
            captured["query"] = req.query
            captured["top_k"] = req.top_k
            captured["rerank"] = req.rerank
            return type("R", (), {
                "success": True, "status_code": 200,
                "documents": [
                    Document(
                        id="d1",
                        content="测试内容",
                    )
                ],
                "elapsed_ms": 1.0, "raw": {}, "error": "",
            })()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _C())


    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", api_key="test-api-key"),
    )

    state = {"messages": [HumanMessage(content="怎么退款？")], "workspace_ids": ["workspace-1"]}
    result = await rag_prefetch_node(state)
    assert captured["query"] == "怎么退款？"
    assert captured["top_k"] == 5
    assert captured["rerank"] is False
    assert "测试内容" in result["rag_context"]


@pytest.mark.asyncio
async def test_rag_prefetch_uses_configured_search_options(monkeypatch):
    captured = {}

    class _Client:
        async def search(self, req, **kwargs):
            captured["top_k"] = req.top_k
            captured["rerank"] = req.rerank
            return type("Result", (), {"success": True, "documents": [], "elapsed_ms": 1.0})()

    monkeypatch.setattr(prefetch_mod.settings, "rag_top_k", 7)
    monkeypatch.setattr(prefetch_mod.settings, "rag_rerank", True)
    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _Client())
    monkeypatch.setattr(auth_mod, "get_current_credential", lambda: AppCredential(app_id="imsdom", api_key=""))

    await rag_prefetch_node({"messages": [HumanMessage(content="怎么退款？")], "workspace_ids": ["workspace-1"]})

    assert captured == {"top_k": 7, "rerank": True}


@pytest.mark.asyncio
async def test_rag_prefetch_uses_rewritten_search_query(monkeypatch):
    captured = {}

    class _C:
        async def search(self, req, **kwargs):
            captured["query"] = req.query
            return type("R", (), {"success": True, "documents": [], "elapsed_ms": 1.0})()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _C())
    monkeypatch.setattr(auth_mod, "get_current_credential", lambda: AppCredential(app_id="imsdom", api_key=""))

    await rag_prefetch_node({
        "messages": [HumanMessage(content="这四个人能住吗？")],
        "search_query": "家庭房能否入住两名成人、一个11岁儿童和一个1岁婴儿？",
        "workspace_ids": ["workspace-1"],
    })

    assert captured["query"] == "家庭房能否入住两名成人、一个11岁儿童和一个1岁婴儿？"


@pytest.mark.asyncio
async def test_rag_prefetch_keeps_workspace_results_separate(monkeypatch):

    requested = []

    class _Client:
        async def search(self, req, **kwargs):
            workspace_id = req.workspace_ids[0]
            requested.append(workspace_id)
            document = type("Document", (), {"content": f"{workspace_id} policy", "metadata": {"filename": f"{workspace_id}.pdf"}})()
            return type("Result", (), {"success": True, "documents": [document], "elapsed_ms": 1.0})()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _Client())
    monkeypatch.setattr(auth_mod, "get_current_credential", lambda: AppCredential(app_id="acme", api_key=""))

    result = await rag_prefetch_node({"messages": [HumanMessage(content="policy")], "workspace_ids": ["ws-a", "ws-b"]})

    assert requested == ["ws-a", "ws-b"]
    assert "[工作区 ws-a]" in result["rag_context"]
    assert "[工作区 ws-b]" in result["rag_context"]
    assert "ws-a.pdf" in result["rag_context"]
    assert "ws-b.pdf" in result["rag_context"]


@pytest.mark.asyncio
async def test_rag_prefetch_rejects_failed_workspace_search(monkeypatch):

    class _Client:
        async def search(self, req, **kwargs):
            return type("Result", (), {"success": False, "status_code": 403, "error": "workspace access denied", "documents": []})()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _Client())
    monkeypatch.setattr(auth_mod, "get_current_credential", lambda: AppCredential(app_id="acme", api_key=""))

    with pytest.raises(RuntimeError, match="workspace access denied"):
        await rag_prefetch_node({"messages": [HumanMessage(content="policy")], "workspace_ids": ["ws-a"]})


@pytest.mark.asyncio
async def test_rag_prefetch_empty_on_exception(monkeypatch):
    """client.search 抛异常时返回检索错误。"""


    class _BadClient:
        async def aclose(self): pass
        async def search(self, req, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _BadClient())


    monkeypatch.setattr(
        auth_mod,
        "get_current_credential",
        lambda: AppCredential(app_id="imsdom", api_key="test-api-key"),
    )

    state = {"messages": [HumanMessage(content="hi")], "workspace_ids": ["workspace-1"]}
    with pytest.raises(RuntimeError, match="connection refused"):
        await rag_prefetch_node(state)


@pytest.mark.asyncio
async def test_rag_prefetch_empty_on_no_human_message():
    """没有 HumanMessage 时返回空 rag_context。"""


    state = {"messages": [AIMessage(content="hi")]}
    result = await rag_prefetch_node(state)
    assert result["rag_context"] == ""


@pytest.mark.asyncio
async def test_rag_prefetch_forwards_selected_workspace(monkeypatch):


    captured = {}

    class _Client:
        async def search(self, req, **kwargs):
            captured["workspace_ids"] = req.workspace_ids
            return type("Result", (), {"success": True, "documents": [], "elapsed_ms": 0})()

    monkeypatch.setattr("chat.src.rag.client.get_rag_client", lambda: _Client())
    monkeypatch.setattr(auth_mod, "get_current_credential", lambda: AppCredential(app_id="acme", api_key=""))

    await rag_prefetch_node({"messages": [HumanMessage(content="policy")], "workspace_ids": ["workspace-1"]})

    assert captured["workspace_ids"] == ["workspace-1"]
