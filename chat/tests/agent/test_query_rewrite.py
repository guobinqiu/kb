from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import chat.src.agent.nodes.query_rewrite as rewrite_mod
from chat.src.agent.nodes.query_rewrite import query_rewrite_node


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_multi_turn_uses_original_question_when_rewrite_disabled(monkeypatch):
    monkeypatch.setattr(rewrite_mod.settings, "rag_query_rewrite", False)
    monkeypatch.setattr(rewrite_mod, "get_llm", lambda: pytest.fail("rewrite is disabled"))

    result = await query_rewrite_node({"messages": [
        HumanMessage(content="我们两大一小。"),
        AIMessage(content="好的。"),
        HumanMessage(content="家庭房呢？"),
    ]})

    assert result == {"search_query": "家庭房呢？"}


@pytest.mark.asyncio
async def test_single_turn_uses_original_question_without_calling_llm(monkeypatch):
    monkeypatch.setattr(rewrite_mod, "get_llm", lambda: pytest.fail("single turn must not call LLM"))

    result = await query_rewrite_node({"messages": [HumanMessage(content="家庭房能住几个人？")]})

    assert result == {"search_query": "家庭房能住几个人？"}


@pytest.mark.asyncio
async def test_multi_turn_rewrites_last_question_with_history(monkeypatch):
    captured = {}
    monkeypatch.setattr(rewrite_mod.settings, "rag_query_rewrite", True)

    class _LLM:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content
            return AIMessage(content="家庭房能否入住两名成人、一个11岁儿童和一个1岁婴儿？")

    monkeypatch.setattr(rewrite_mod, "get_llm", lambda: _LLM())
    result = await query_rewrite_node({
        "messages": [
            HumanMessage(content="我们两大一小，小孩11岁，大床房能住吗？"),
            AIMessage(content="可以。"),
            HumanMessage(content="那再带一个一岁宝宝，加婴儿床就行吧？"),
            AIMessage(content="不可以。"),
            HumanMessage(content="换家庭房能把这四个人都住下吗？"),
        ]
    })

    assert "换家庭房能把这四个人都住下吗？" in captured["prompt"]
    assert "保持最后一个用户问题使用的语言" in captured["prompt"]
    assert result == {"search_query": "家庭房能否入住两名成人、一个11岁儿童和一个1岁婴儿？"}


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_to_last_question(monkeypatch):
    monkeypatch.setattr(rewrite_mod.settings, "rag_query_rewrite", True)
    class _LLM:
        async def ainvoke(self, messages):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(rewrite_mod, "get_llm", lambda: _LLM())
    result = await query_rewrite_node({
        "messages": [
            HumanMessage(content="我们两大一小。"),
            AIMessage(content="好的。"),
            HumanMessage(content="家庭房呢？"),
        ]
    })

    assert result == {"search_query": "家庭房呢？"}
