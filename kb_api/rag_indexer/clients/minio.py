from __future__ import annotations

import os
from datetime import timedelta
from urllib.parse import urlparse

from minio import Minio

from kb_api.rag_indexer.common.config import StorageConfig
from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from kb_api.rag_indexer.core.index.service import parse_s3_url


def presign_object(config: StorageConfig, s3_url: str, expires_in: int = 3600) -> str:
    try:
        bucket, object_name = parse_s3_url(s3_url)
    except ValueError as exc:
        raise UpstreamServiceError(service="presign", error=str(exc), retryable=False, status_code=400) from exc
    client = minio_client(config)
    try:
        return client.presigned_get_object(bucket, object_name, expires=timedelta(seconds=expires_in))
    except Exception as exc:
        raise UpstreamServiceError(service="presign", error=str(exc), retryable=False, status_code=500) from exc


def minio_client(config: StorageConfig) -> Minio:
    if not config.endpoint_url:
        raise UpstreamServiceError(
            service="presign", error="object storage is not configured", retryable=False, status_code=503,
        )
    parsed = urlparse(config.endpoint_url)
    endpoint = parsed.netloc or parsed.path
    return Minio(
        endpoint,
        access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        secure=parsed.scheme == "https",
    )
