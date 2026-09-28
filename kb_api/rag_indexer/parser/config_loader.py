from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from kb_api.rag_indexer.parser.common.config import MineruApiServerConfig, MineruCloudParserConfig, ParserConfig, RetryConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config/rag.yaml"


def load_parser_config(config_file: str | Path | None = None) -> ParserConfig:
    with _resolve_config_path(config_file or os.environ.get("KB_CONFIG_FILE")).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    parser = raw.get("parser") or {}
    active = _select_enabled_backend(parser, ("mineru_cloud", "mineru"))
    cloud = parser.get("mineru_cloud") or {}
    api = parser.get("mineru") or {}
    return ParserConfig(
        active=active,
        download_timeout=int(parser.get("download_timeout", 60)),
        mineru=MineruApiServerConfig(
            enable=active == "mineru",
            base_url=api.get("base_url", "http://mineru-api-server:8000"),
            timeout=int(api.get("timeout", 300)),
            tier=api.get("tier", "standard"),
            parse_method=api.get("parse_method", "auto"),
            retry=_parse_retry_config(api.get("retry")),
        ),
        mineru_cloud=MineruCloudParserConfig(
            enable=active == "mineru_cloud",
            base_url=cloud.get("base_url", "https://mineru.net"),
            timeout=int(cloud.get("timeout", 300)),
            model_version=cloud.get("model_version", "vlm"),
            enable_formula=bool(cloud.get("enable_formula", True)),
            enable_table=bool(cloud.get("enable_table", True)),
            language=cloud.get("language", "ch"),
            retry=_parse_retry_config(cloud.get("retry")),
            api_key=_env_value("MINERU_API_KEY"),
        ),
    )


def _select_enabled_backend(parser: dict[str, Any], names: tuple[str, ...]) -> str:
    backends = {
        name: parser.get(name)
        for name in names
        if isinstance(parser.get(name), dict)
    }
    enabled = [name for name, config in backends.items() if bool(config.get("enable"))]
    if len(enabled) != 1:
        raise ValueError("parser must enable exactly one backend")
    return enabled[0]


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


def _resolve_config_path(value: str | Path | None) -> Path:
    if value is None:
        return DEFAULT_CONFIG_FILE
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] in ("rag", "services"):
        return PROJECT_ROOT / path
    return Path.cwd() / path


def _env_value(name: str) -> str | None:
    import os

    value = os.environ.get(name)
    return value if value else None
