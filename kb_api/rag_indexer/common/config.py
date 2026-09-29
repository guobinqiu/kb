from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class VectorServiceConfig:
    provider: str
    base_url: str | None = None
    timeout: int = 30
    query_timeout: int = 10
    write_timeout: int = 60
    init_timeout: int = 120
    drop_timeout: int = 180
    retry: RetryConfig = field(default_factory=RetryConfig)
    quantization: QdrantQuantizationConfig | None = None
    api_key: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class TextParserConfig:
    chunk_size: int = 500
    chunk_overlap: int = 80


@dataclass(frozen=True)
class ChunkingConfig:
    text: TextParserConfig = field(default_factory=TextParserConfig)


@dataclass(frozen=True)
class ServiceClientsConfig:
    vector: VectorServiceConfig | None = None


@dataclass(frozen=True)
class StorageConfig:
    endpoint_url: str | None = None
    bucket: str = "rag"
    presign_timeout: int = 60


@dataclass(frozen=True)
class CallbackConfig:
    url: str = "http://kb_api:6100/api/v1/index-results"
    timeout: float = 10


@dataclass(frozen=True)
class IndexerConfig:
    callback: CallbackConfig = field(default_factory=CallbackConfig)


@dataclass(frozen=True)
class AppConfig:
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    services: ServiceClientsConfig = field(default_factory=ServiceClientsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    available_components: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name: str = ""


def parse_app_config(raw: dict[str, Any]) -> AppConfig:
    services = raw.get("services") or {}
    services_config = _parse_service_clients_config(services)
    storage = raw.get("storage") or {}
    callback = (raw.get("indexer") or {}).get("callback") or {}
    if services_config.vector is None:
        raise ValueError("services.vector is required")
    return AppConfig(
        indexer=IndexerConfig(callback=CallbackConfig(
            url=str(callback.get("url", "http://kb_api:6100/api/v1/index-results")),
            timeout=float(callback.get("timeout", 10)),
        )),
        chunking=_parse_chunking_config(raw.get("chunking") or {}),
        services=services_config,
        storage=StorageConfig(
            endpoint_url=storage.get("endpoint_url"),
            bucket=str(storage.get("bucket", "rag")),
            presign_timeout=int(storage.get("presign_timeout", 60)),
        ),
    )


def _parse_chunking_config(raw: dict[str, Any]) -> ChunkingConfig:
    text = raw.get("text") or {}
    return ChunkingConfig(
        text=TextParserConfig(
            chunk_size=int(text.get("chunk_size", 500)),
            chunk_overlap=int(text.get("chunk_overlap", 80)),
        ),
    )


def _parse_qdrant_quantization(quantization) -> QdrantQuantizationConfig | None:
    if not isinstance(quantization, dict):
        return None
    return QdrantQuantizationConfig(
        enable=_bool(quantization.get("enable", False)),
        type=str(quantization.get("type", "int8")),
        quantile=float(quantization["quantile"]) if quantization.get("quantile") is not None else None,
        always_ram=_bool(quantization["always_ram"]) if quantization.get("always_ram") is not None else None,
    )


def _parse_service_clients_config(raw: dict[str, Any]) -> ServiceClientsConfig:
    vector = raw.get("vector")
    return ServiceClientsConfig(
        vector=_parse_vector_service_config(vector) if isinstance(vector, dict) else None,
    )


def _parse_vector_service_config(raw: dict[str, Any]) -> VectorServiceConfig:
    provider = str(_required(raw, "provider", "services.vector"))
    _validate_supported("services.vector.provider", provider, {"qdrant", "milvus", "qdrant_cloud", "milvus_cloud"})
    _required(raw, "base_url", "services.vector")
    timeout = int(raw.get("timeout", 30))
    return VectorServiceConfig(
        provider=provider.removesuffix("_cloud"),
        base_url=raw.get("base_url"),
        timeout=timeout,
        query_timeout=int(raw.get("query_timeout", timeout)),
        write_timeout=int(raw.get("write_timeout", timeout)),
        init_timeout=int(raw.get("init_timeout", timeout)),
        drop_timeout=int(raw.get("drop_timeout", timeout)),
        retry=_parse_retry_config(raw.get("retry")),
        quantization=_parse_qdrant_quantization(raw.get("quantization")),
        api_key=raw.get("api_key"),
        token=raw.get("token"),
    )


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    if not isinstance(raw, dict):
        raise ValueError("retry config must be an object")
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"invalid boolean value: {value}")


def _component_name(value: Any, section_name: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{section_name} is required")
    name = value.get("name")
    if name is None:
        raise ValueError(f"{section_name}.name is required")
    return name


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _validate_supported(name: str, value: str, supported: set[str]) -> None:
    if value not in supported:
        raise ValueError(f"unsupported {name}: {value}")
