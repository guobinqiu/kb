from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kb_api.rag_indexer.common.config import RetryConfig
from kb_api.rag_indexer.inference.models import EmbeddingSpec


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config/rag.yaml"


@dataclass(frozen=True)
class SiliconFlowConfig:
    base_url: str
    api_key: str | None = field(repr=False)
    dense_model: str
    dimensions: int | None = None
    dense_timeout: int = 60
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class TeiConfig:
    dense_url: str
    dense_model: str
    dimensions: int | None = None
    dense_timeout: float = 60.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    batch_size: int = 32


@dataclass(frozen=True)
class DenseModelConfig:
    provider: str
    model: str
    dimensions: int | None
    base_url: str
    timeout: float
    api_key: str | None = field(default=None, repr=False)
    retry: RetryConfig = field(default_factory=RetryConfig)
    batch_size: int = 32


@dataclass(frozen=True)
class InferenceConfig:
    siliconflow: SiliconFlowConfig | None = None
    tei: TeiConfig | None = None
    dense_models: tuple[DenseModelConfig, ...] = ()
    embedding: EmbeddingSpec | None = None


def load_inference_config(config_file: str | Path | None = None) -> InferenceConfig:
    with _resolve_config_path(config_file or os.environ.get("KB_CONFIG_FILE")).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    inference = raw.get("inference")
    dense_models = _load_dense_models(inference)
    selected = _selected_provider(inference)
    dense = _selected_dense(selected)
    embedding = _embedding_spec(selected, dense)
    if _provider_name(selected) == "siliconflow":
        return InferenceConfig(siliconflow=SiliconFlowConfig(
            base_url=_required(selected, "base_url", "siliconflow"),
            api_key=os.environ[_siliconflow_api_key_env(selected["name"])],
            dense_model=dense["model_name"],
            dimensions=dense.get("dimensions"),
            dense_timeout=int(dense.get("timeout", 60)),
            retry=_parse_retry_config(selected.get("retry")),
        ), dense_models=dense_models, embedding=embedding)
    if _provider_name(selected) == "tei":
        return InferenceConfig(tei=TeiConfig(
            dense_url=_required(dense, "base_url", "dense"),
            dense_model=dense["model_name"],
            dimensions=dense.get("dimensions"),
            dense_timeout=float(dense.get("timeout", 60)),
            retry=_parse_retry_config(selected.get("retry")),
            batch_size=int(dense.get("batch_size", 32)),
        ), dense_models=dense_models, embedding=embedding)
    raise ValueError(f"unsupported inference provider: {selected['name']}")


def _load_dense_models(raw: Any) -> tuple[DenseModelConfig, ...]:
    if not isinstance(raw, dict):
        raise ValueError("inference must enable at least one component")
    models = []
    for provider, provider_config in raw.items():
        if not isinstance(provider_config, dict) or not _bool(provider_config.get("enable", False)):
            continue
        provider_type = _provider_name({"name": provider})
        base_url = provider_config.get("base_url")
        retry = _parse_retry_config(provider_config.get("retry"))
        for dense in _enabled_components(provider_config.get("dense")):
            model_base_url = dense.get("base_url") or base_url
            if not model_base_url:
                raise ValueError(f"{provider} dense.base_url is required")
            api_key = os.environ[_siliconflow_api_key_env(provider)] if provider_type == "siliconflow" else None
            models.append(DenseModelConfig(
                provider=provider,
                model=_required(dense, "model_name", "dense"),
                dimensions=dense.get("dimensions"),
                base_url=model_base_url,
                timeout=float(dense.get("timeout", 60)),
                api_key=api_key,
                retry=retry,
                batch_size=int(dense.get("batch_size", 32)),
            ))
    if not models:
        raise ValueError("dense must enable at least one component")
    return tuple(models)


def _selected_provider(raw: Any) -> dict[str, Any]:
    return _select_enabled(raw, "inference", required=True)


def _selected_dense(provider: dict[str, Any]) -> dict[str, Any]:
    return _select_enabled(provider.get("dense"), "dense", required=True)


def _embedding_spec(provider: dict[str, Any], dense: dict[str, Any]) -> EmbeddingSpec | None:
    dimensions = dense.get("dimensions")
    if dimensions is None:
        return None
    return EmbeddingSpec(
        provider=str(provider["name"]),
        model=str(_required(dense, "model_name", "dense")),
        dimensions=int(dimensions),
    )


def _enabled_components(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    return [dict(config) for config in raw.values() if isinstance(config, dict) and _bool(config.get("enable", False))]


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    if not isinstance(raw, dict):
        raise ValueError("retry config must be an object")
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


def _provider_name(selected: dict[str, Any]) -> str:
    name = str(selected.get("name", ""))
    if name.startswith("siliconflow-"):
        return "siliconflow"
    return name


def _siliconflow_api_key_env(name: str) -> str:
    if name == "siliconflow-cn":
        return "SILICONFLOW_CN_API_KEY"
    if name == "siliconflow-intl":
        return "SILICONFLOW_INTL_API_KEY"
    raise ValueError(f"unsupported siliconflow provider: {name}")


def _select_enabled(raw: Any, section_name: str, *, required: bool) -> dict[str, Any] | None:
    if raw is None:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        return None
    if not isinstance(raw, dict):
        raise ValueError("component config must be an object")
    if "name" in raw or "type" in raw:
        return raw
    enabled = [
        (name, dict(config))
        for name, config in raw.items()
        if isinstance(config, dict) and _bool(config.get("enable", False))
    ]
    if not enabled:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        return None
    if len(enabled) != 1:
        if required:
            raise ValueError(f"{section_name} must enable exactly one component")
        raise ValueError(f"{section_name} must enable at most one component")
    name, config = enabled[0]
    config.pop("enable", None)
    config.setdefault("name", name)
    config.setdefault("type", name)
    return config


def _resolve_config_path(value: str | Path | None) -> Path:
    if value is None:
        return DEFAULT_CONFIG_FILE
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / path
    return Path.cwd() / path


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
