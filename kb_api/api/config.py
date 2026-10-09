from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


def _validate_credential(
    name: str, value: str, *, forbidden: set[str], min_length: int | None = None,
) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    if value.lower() in forbidden:
        raise ValueError(f"{name} uses an unsafe placeholder")
    if min_length is not None and len(value) < min_length:
        raise ValueError(f"{name} must be at least {min_length} bytes")
    return value


@dataclass(frozen=True)
class ApiLimits:
    rate_limit: str = "120/minute"
    rate_limit_index: str = "10/minute"


def load_api_limits(path: str | Path | None = None) -> ApiLimits:
    config_path = Path(path or os.getenv("KB_CONFIG_FILE", Path(__file__).parent.parent / "config/rag.yaml"))
    with config_path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    api = raw.get("api") or {}
    return ApiLimits(
        rate_limit=str(api.get("rate_limit", "120/minute")),
        rate_limit_index=str(api.get("rate_limit_index", "10/minute")),
    )


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://rag:rag@postgres:5432/rag"
    token_secret: str = ""
    token_ttl_seconds: int = 86400
    admin_name: str = "admin"
    admin_password: str = ""
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "kb-files"
    minio_secure: bool = False
    minio_public_url: str = "http://localhost:9000"
    rabbitmq_url: str = "amqp://admin:admin123@rabbitmq:5672/%2F"

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_secret", _validate_credential(
            "JWT_SECRET", self.token_secret, forbidden={"change-me"},
        ))
        object.__setattr__(self, "admin_password", _validate_credential(
            "KB_ADMIN_PASSWORD", self.admin_password, min_length=8, forbidden={"admin", "change-me"},
        ))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("KB_DATABASE_URL", cls.database_url),
            token_secret=os.getenv("JWT_SECRET", ""),
            token_ttl_seconds=int(os.getenv("KB_TOKEN_TTL_SECONDS", str(cls.token_ttl_seconds))),
            admin_name=os.getenv("KB_ADMIN_NAME", cls.admin_name),
            admin_password=os.getenv("KB_ADMIN_PASSWORD", ""),
            minio_endpoint=os.getenv("KB_MINIO_ENDPOINT", cls.minio_endpoint),
            minio_access_key=os.getenv("KB_MINIO_ACCESS_KEY", cls.minio_access_key),
            minio_secret_key=os.getenv("KB_MINIO_SECRET_KEY", cls.minio_secret_key),
            minio_bucket=os.getenv("KB_MINIO_BUCKET", cls.minio_bucket),
            minio_secure=os.getenv("KB_MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
            minio_public_url=os.getenv("KB_MINIO_PUBLIC_URL", cls.minio_public_url),
            rabbitmq_url=os.getenv("KB_RABBITMQ_URL", cls.rabbitmq_url),
        )
