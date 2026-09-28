from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException
from minio import Minio

from kb_api.rag_indexer.common.config import StorageConfig
from kb_api.rag_indexer.core.api.schemas import FileIndexRequest, PresignRequest
from kb_api.rag_indexer.core.api.services.common import app_principal, require_ready, scoped_vector, vector_scope
from kb_api.rag_indexer.core.auth import Principal
from kb_api.rag_indexer.core.index import index_presigned_file
from kb_api.rag_indexer.core.index.service import filename_from_s3_url, parse_s3_url, validate_supported_file_extension
from kb_api.rag_indexer.common.tracing import get_trace_id
from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from kb_api.rag_indexer.core.index.errors import index_error_detail, index_stage
from kb_api.rag_indexer.core.embedding import embedding_scope, resolve_embedding


def index_file(state, req: FileIndexRequest, principal: Principal):
    file_id = req.file_id or _new_file_id()
    effective_principal = app_principal(principal, req.app_id)
    try:
        require_ready(state)
        filename = req.filename or filename_from_s3_url(req.s3_url)
        validate_supported_file_extension(Path(filename).suffix.lower())
        spec = resolve_embedding(state, req.embedding)
        with embedding_scope(state, spec), vector_scope(state, effective_principal):
            presigned_url = _resolve_presigned_url(
                state,
                effective_principal.app_id,
                file_id,
                req.s3_url,
                filename,
                req.presigned_url,
            )
            count, _ = index_presigned_file(
                state,
                file_id=file_id,
                presigned_url=presigned_url,
                s3_url=req.s3_url,
                filename=filename,
            )
        return {
            "success": True,
            "error": None,
            "service": None,
            "retryable": False,
            "traceId": get_trace_id(),
            "file_id": file_id,
            "chunk_count": count,
        }
    except Exception as exc:
        error = _error_detail(exc)
        raise HTTPException(error.status_code, index_error_detail(error, file_id)) from exc


def presign_object(state, req: PresignRequest):
    bucket, object_name = parse_storage_url(req.s3_url)
    client = minio_client(state.config.storage)
    try:
        url = client.presigned_get_object(bucket, object_name, expires=timedelta(seconds=req.expires_in))
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"presigned_url": url}


def client_presign_object(state, req: PresignRequest, principal: Principal):
    bucket, object_name = parse_storage_url(req.s3_url)
    if bucket != state.config.storage.bucket or not object_name.startswith(storage_prefix(principal.app_id)):
        raise HTTPException(403, "file does not belong to this app")
    return presign_object(state, req)


def dense_vector(state, app_id: str, chunk_id: str, principal: Principal):
    require_ready(state)
    effective_principal = app_principal(principal, app_id)
    method = getattr(state.vector_client, "get_dense_vector", None)
    if not callable(method):
        raise HTTPException(400, "dense vector is not supported by current vector")
    with vector_scope(state, effective_principal):
        vector = method(chunk_id)
    if vector is None:
        raise HTTPException(404, "chunk not found")
    return {"chunk_id": chunk_id, "type": "dense", "vector": vector}


def client_delete_file(state, file_id: str, principal: Principal):
    require_ready(state)
    vector = scoped_vector(state, principal)
    deleted_chunks = vector.delete_file_chunks(file_id)
    return {"deleted_chunks": deleted_chunks}


def _resolve_presigned_url(state, app_id: str, file_id: str, s3_url: str, filename: str, presigned_url: str | None) -> str:
    if presigned_url:
        return presigned_url
    with index_stage("presign", "presign"):
        return presign_object(
            state,
            PresignRequest(s3_url=s3_url, expires_in=max(60, state.config.storage.presign_timeout)),
        )["presigned_url"]


def parse_storage_url(s3_url: str) -> tuple[str, str]:
    try:
        return parse_s3_url(s3_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def minio_client(config: StorageConfig) -> Minio:
    _require_storage(config)
    parsed = urlparse(config.endpoint_url)
    endpoint = parsed.netloc or parsed.path
    return Minio(
        endpoint,
        access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        secure=parsed.scheme == "https",
    )


def storage_prefix(app_id: str) -> str:
    return f"uploads/{app_id}/"


def _require_storage(config: StorageConfig) -> None:
    if not config.endpoint_url:
        raise HTTPException(503, "object storage is not configured")


def _new_file_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _error_detail(exc: Exception) -> UpstreamServiceError:
    if isinstance(exc, UpstreamServiceError):
        return exc
    if isinstance(exc, HTTPException):
        return UpstreamServiceError(service="rag_indexer", error=str(exc.detail), retryable=False, status_code=exc.status_code)
    if isinstance(exc, ValueError):
        return UpstreamServiceError(service="rag_indexer", error=str(exc), retryable=False, status_code=400)
    return UpstreamServiceError(service="rag_indexer", error=str(exc) or None, retryable=False, status_code=500)
