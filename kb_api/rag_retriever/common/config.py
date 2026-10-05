from dataclasses import dataclass, field
from pathlib import Path

import yaml
import os


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    interval_seconds: float = 0.5


@dataclass(frozen=True)
class QdrantQuantizationConfig:
    enable: bool = False
    type: str = "int8"
    quantile: float | None = None
    always_ram: bool | None = None


@dataclass(frozen=True)
class VectorConfig:
    provider: str
    bm25: bool = False
    base_url: str | None = None
    timeout: int = 30
    query_timeout: int = 10
    init_timeout: int = 120
    drop_timeout: int = 180
    retry: RetryConfig = field(default_factory=RetryConfig)
    quantization: QdrantQuantizationConfig | None = None
    api_key: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class SearchConfig:
    mode: str = "dense"
    top_k: int = 5
    rerank_fetch_k: int = 20
    rerank: bool = False
    rrf_k: int = 60
    hybrid_fetch_k: int = 20


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "kb_api/config/rag.yaml"


def load_vector_config(path: str | Path | None = None) -> VectorConfig:
    configured_path = path or os.environ.get("KB_CONFIG_FILE")
    config_path = Path(configured_path) if configured_path else DEFAULT_CONFIG_FILE
    if not config_path.is_absolute() and not config_path.exists():
        if config_path.parts and config_path.parts[0] in ("rag", "services"):
            config_path = PROJECT_ROOT / "kb_api" / config_path
        else:
            raise FileNotFoundError(str(config_path))
    with config_path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    backends = raw["vector_db"]
    providers = ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud")
    enabled = [
        (name, backends[name])
        for name in providers
        if isinstance(backends.get(name), dict) and bool(backends[name].get("enable"))
    ]
    if len(enabled) != 1:
        raise ValueError("vector backend must enable exactly one component")
    name, selected = enabled[0]
    provider = str(selected.get("provider", name))
    if selected.get("provider", name) is None:
        raise ValueError("services.vector.provider is required")
    if provider not in providers:
        raise ValueError(f"unsupported services.vector.provider: {provider}")
    if selected.get("base_url") is None:
        raise ValueError("services.vector.base_url is required")
    timeout = int(selected.get("timeout", 30))
    retry = selected.get("retry")
    if retry is None:
        retry_config = RetryConfig()
    else:
        if not isinstance(retry, dict):
            raise ValueError("retry config must be an object")
        retry_config = RetryConfig(
            max_attempts=max(1, int(retry.get("max_attempts", 3))),
            interval_seconds=max(0.0, float(retry.get("interval_seconds", 0.5))),
        )
    quantization = selected.get("quantization")
    quantization_config = None
    if isinstance(quantization, dict):
        quantization_config = QdrantQuantizationConfig(
            enable=_bool(quantization.get("enable", False)),
            type=str(quantization.get("type", "int8")),
            quantile=float(quantization["quantile"]) if quantization.get("quantile") is not None else None,
            always_ram=_bool(quantization["always_ram"]) if quantization.get("always_ram") is not None else None,
        )
    secret_env = {
        "qdrant": "QDRANT_API_KEY",
        "milvus": "MILVUS_TOKEN",
        "qdrant_cloud": "QDRANT_CLOUD_API_KEY",
        "milvus_cloud": "MILVUS_CLOUD_TOKEN",
    }
    return VectorConfig(
        provider=provider.removesuffix("_cloud"),
        bm25=_bool(selected.get("bm25", provider.startswith("milvus"))),
        base_url=selected.get("base_url"),
        timeout=timeout,
        query_timeout=int(selected.get("query_timeout", timeout)),
        init_timeout=int(selected.get("init_timeout", timeout)),
        drop_timeout=int(selected.get("drop_timeout", timeout)),
        retry=retry_config,
        quantization=quantization_config,
        api_key=os.getenv(secret_env[provider]) if provider.startswith("qdrant") else None,
        token=os.getenv(secret_env[provider]) if provider.startswith("milvus") else None,
    )


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"invalid boolean value: {value}")


def load_search_config(path: str | Path | None = None) -> SearchConfig:
    configured_path = path or os.environ.get("KB_CONFIG_FILE")
    config_path = Path(configured_path) if configured_path else DEFAULT_CONFIG_FILE
    with config_path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    raw = raw.get("search", raw)
    hybrid = raw.get("hybrid") or {}
    return SearchConfig(
        mode=str(raw.get("mode", "dense")),
        top_k=int(raw.get("top_k", 5)),
        rerank_fetch_k=int(raw.get("rerank_fetch_k", 20)),
        rerank=bool(raw.get("rerank", False)),
        rrf_k=int(hybrid.get("rrf_k", raw.get("rrf_k", 60))),
        hybrid_fetch_k=int(hybrid.get("fetch_k", 20)),
    )
