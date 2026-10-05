import pytest

import chat.src.agent.llm as llm_mod
import chat.src.config as config_mod
from chat.src.agent.nodes import llm as llm_node
from chat.src.config import settings


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("database_env", [None, "postgresql://test:test@localhost:5432/test"])
def test_create_llm_uses_yaml_behavior_and_environment_connections(monkeypatch, tmp_path, database_env):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    if database_env is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_env)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://wrong-llm.example/v1")
    monkeypatch.setenv("MODEL_NAME", "ignored-model")
    monkeypatch.setenv("RAG_BASE_URL", "http://wrong-rag.example:6000")
    monkeypatch.setenv("LLM_TIMEOUT", "1")
    monkeypatch.setenv("RAG_TIMEOUT", "1")

    config_path = tmp_path / "chat.yaml"
    config_path.write_text(
        "openai_base_url: http://llm.example/v1\n"
        "model_name: test-model\n"
        "prompt: Test assistant\n"
        "database_url: postgresql://rag:rag@postgres:5432/rag\n"
        "request:\n"
        "  timeout: 45\n"
        "model:\n"
        "  timeout: 55\n"
        "rag:\n"
        "  base_url: http://rag.example:6000\n"
        "  timeout: 12.5\n"
        "  top_k: 7\n"
        "  rerank: true\n"
        "  query_rewrite: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_path, raising=False)
    monkeypatch.chdir(tmp_path)
    settings = config_mod.Settings()
    monkeypatch.setattr(llm_mod, "settings", settings)

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_mod, "ChatOpenAI", FakeChatOpenAI)

    llm_mod.create_llm()

    assert captured["timeout"] == 55
    assert captured["base_url"] == "http://llm.example/v1"
    assert captured["model"] == "test-model"
    assert captured["api_key"] == "test-key"
    assert settings.rag_base_url == "http://rag.example:6000"
    assert settings.prompt == "Test assistant"
    assert settings.request_timeout == 45
    assert settings.model_timeout == 55
    assert settings.rag_timeout == 12.5
    assert settings.rag_top_k == 7
    assert settings.rag_rerank is True
    assert settings.rag_query_rewrite is False
    assert settings.database_url == (database_env or "postgresql://rag:rag@postgres:5432/rag")


async def test_semaphore_uses_settings_and_reuses_initialized_instance(monkeypatch):

    monkeypatch.setenv("LLM_CONCURRENCY_LIMIT", "99")
    monkeypatch.setattr(settings, "llm_concurrency_limit", 2)
    monkeypatch.setattr(llm_node, "_semaphore", None)

    semaphore = llm_node.get_semaphore()
    assert llm_node.get_semaphore() is semaphore
    async with semaphore:
        assert not semaphore.locked()
        async with semaphore:
            assert semaphore.locked()
    assert not semaphore.locked()

    llm_node.init_semaphore(1)
    initialized = llm_node.get_semaphore()
    assert initialized is not semaphore
    assert llm_node.get_semaphore() is initialized
    async with initialized:
        assert initialized.locked()
