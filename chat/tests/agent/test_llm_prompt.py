from datetime import datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage

import chat.src.agent.nodes.llm as llm_mod
from chat.src.config import Settings, _load_settings


@pytest.mark.unit
def test_prompt_is_loaded_from_config():

    values = _load_settings()
    assert values["prompt"].strip()
    assert Settings().prompt == values["prompt"]


@pytest.mark.unit
def test_settings_read_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-at-least-32-bytes-long")

    assert _load_settings()["token_secret"] == "jwt-secret-at-least-32-bytes-long"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("rag_context", ["", "Reference document"])
async def test_prompt_and_time_refresh_without_changing_history(monkeypatch, rag_context):
    moments = iter([
        datetime(2026, 9, 20, 23, 59, 59),
        datetime(2026, 9, 21, 0, 0, 1),
    ])

    class Clock:
        @classmethod
        def now(cls):
            return next(moments)

    calls = []

    class FakeLLM:
        async def astream(self, messages):
            calls.append(messages)
            yield AIMessageChunk(content="answer")

    monkeypatch.setattr(llm_mod, "datetime", Clock)
    monkeypatch.setattr(llm_mod, "settings", SimpleNamespace(prompt="Configured prompt"))
    monkeypatch.setattr(llm_mod, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(llm_mod, "safe_get_writer", lambda: None)
    monkeypatch.setattr(llm_mod, "write_reply", lambda *args: None)
    monkeypatch.setattr(llm_mod, "_semaphore", None)
    llm_mod.init_semaphore(1)
    history = [HumanMessage(content="What day is it?")]
    state = {"messages": history, "rag_context": rag_context}

    for _ in range(2):
        result = await llm_mod.llm_node(state)
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "answer"

    for messages in calls:
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content.startswith("Configured prompt")
        assert "Asia/Shanghai" not in messages[0].content
        assert ("## 参考资料" in messages[0].content) == bool(rag_context)
        if rag_context:
            assert rag_context in messages[0].content
        assert messages[1:] == history
    assert "2026-09-20 23:59:59，星期日" in calls[0][0].content
    assert "2026-09-21 00:00:01，星期一" in calls[1][0].content
    assert state["messages"] is history
    assert len(history) == 1
