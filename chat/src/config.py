import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "chat.yaml"


def _load_settings() -> dict:
    with CONFIG_FILE.open(encoding="utf-8") as config_file:
        values = yaml.safe_load(config_file)
    request = values.pop("request", {}) or {}
    model = values.pop("model", {}) or {}
    rag = values.pop("rag", {}) or {}
    values["request_timeout"] = request.get("timeout", 60)
    values["model_timeout"] = model.get("timeout", values["request_timeout"])
    values["rag_base_url"] = rag.get("base_url")
    values["rag_timeout"] = rag.get("timeout", 10.0)
    values["rag_max_retries"] = rag.get("max_retries", 2)
    values["rag_top_k"] = rag.get("top_k", 5)
    values["rag_rerank"] = rag.get("rerank", False)
    values["rag_query_rewrite"] = rag.get("query_rewrite", True)
    values["openai_api_key"] = os.getenv("OPENAI_API_KEY")
    values["token_secret"] = os.getenv("KB_TOKEN_SECRET")
    values["database_url"] = os.getenv("DATABASE_URL") or values.get("database_url")
    return values


class Settings(BaseSettings):
    # ─── LLM（OpenAI 兼容端点：OpenRouter / 本地 vLLM） ───────────────────
    openai_api_key: str
    token_secret: str
    openai_base_url: str
    model_name: str = "openai/gpt-4o-mini"
    llm_kwargs: str = ""
    use_responses_api: bool = False
    prompt: str

    # ─── 并发 ──────────────────────────────────────────────────────
    llm_concurrency_limit: int = 10

    # ─── HTTP 层 ────────────────────────────────────────────────────
    request_timeout: int = 60
    model_timeout: int = 60

    # ─── CORS / Rate Limiting ────────────────────────────────────────
    cors_origins: list[str] = ["*"]
    rate_limit_default: str = "100/minute"
    rate_limit_chat: str = "30/minute"
    rate_limit_history: str = "60/minute"
    rate_limit_storage: str = "memory://"
    database_url: str

    # ─── 外部 RAG 服务（核心新增） ───────────────────────────────────
    rag_base_url: str
    rag_timeout: float = 10.0
    rag_max_retries: int = 2
    rag_top_k: int = 5
    rag_rerank: bool = False
    rag_query_rewrite: bool = True

    model_config = SettingsConfigDict(hide_input_in_errors=True)

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings,
    ):
        return init_settings, _load_settings


settings = Settings()
