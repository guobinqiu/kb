from __future__ import annotations

import os
from pathlib import Path

import yaml

from kb_api.rag_indexer.common.config import AppConfig, parse_app_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


CONFIG_FILE_ENV = "KB_CONFIG_FILE"
VECTOR_SERVICES = ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud", "postgres")


def load_app_config() -> AppConfig:
    config_path = os.getenv(CONFIG_FILE_ENV, str(PROJECT_ROOT / "config/rag.yaml"))
    return load_config_file(_resolve_config_path(config_path))


def load_config_file(path: str | Path) -> AppConfig:
    config_path = _resolve_config_path(str(path))
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    available_components = _available_components(raw)
    _select_enabled_components(raw)
    _apply_environment(raw)
    config = parse_app_config(raw)
    object.__setattr__(config, "name", config_path.stem)
    object.__setattr__(config, "available_components", available_components)
    return config

def _resolve_config_path(value: str) -> Path:
    config_path = Path(value)
    if config_path.is_absolute() or config_path.exists():
        return config_path
    if config_path.parts and config_path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / config_path
    raise FileNotFoundError(value)


def _apply_environment(raw: dict) -> None:
    services = raw.get("services")
    if isinstance(services, dict):
        vector = services["vector"]
        vector["api_key"] = None
        vector["token"] = None
        for provider, key, secret_env in (
            ("qdrant", "api_key", "QDRANT_API_KEY"),
            ("milvus", "token", "MILVUS_TOKEN"),
            ("qdrant_cloud", "api_key", "QDRANT_CLOUD_API_KEY"),
            ("milvus_cloud", "token", "MILVUS_CLOUD_TOKEN"),
        ):
            if vector.get("provider") == provider:
                vector[key] = os.getenv(secret_env)
                break
def _select_enabled_components(raw: dict) -> None:
    vector_backends = {
        name: raw["vector_db"].get(name)
        for name in VECTOR_SERVICES
        if isinstance(raw["vector_db"].get(name), dict)
    }
    raw["services"] = {
        "vector": _select_one_enabled(vector_backends, "vector backend", provider_from_key=True),
    }

def _select_one_enabled(section: dict, section_name: str, provider_from_key: bool = False) -> dict:
    enabled = [
        (name, config)
        for name, config in section.items()
        if isinstance(config, dict) and bool(config.get("enable"))
    ]
    if len(enabled) != 1:
        raise ValueError(f"{section_name} must enable exactly one component")
    name, config = enabled[0]
    selected = dict(config)
    if provider_from_key:
        selected.setdefault("provider", name)
    return selected


def _available_components(raw: dict) -> dict[str, list[dict[str, object]]]:
    components = {
        "parser": [{"name": "parser", "model_name": None, "active": True}],
        "inference": [{"name": "inference", "model_name": None, "active": True}],
    }
    vector_backends = {
        name: raw["vector_db"].get(name)
        for name in VECTOR_SERVICES
        if isinstance(raw["vector_db"].get(name), dict)
    }
    components["vector"] = _component_group_options(vector_backends)
    return components


def _component_options(section) -> list[dict[str, object]]:
    if not isinstance(section, dict):
        return []
    if _is_component_group(section):
        return _component_group_options(section)
    return [{
        "name": section.get("name") or section.get("type") or section.get("module"),
        "model_name": section.get("model_name"),
        "active": True,
    }]


def _component_group_options(section) -> list[dict[str, object]]:
    options = []
    for name, config in section.items():
        if not isinstance(config, dict):
            continue
        options.append({
            "name": config.get("name") or config.get("type") or config.get("module") or name,
            "model_name": config.get("model_name"),
            "active": bool(config.get("enable")),
        })
    return options


def _is_component_group(section) -> bool:
    if not isinstance(section, dict):
        return False
    if any(key in section for key in ("name", "type", "module")):
        return False
    return all(isinstance(value, dict) for value in section.values())
