from __future__ import annotations

import uuid
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from kb_api.rag_indexer.core.index.chunking import parser_blocks_to_chunks
from kb_api.rag_indexer.common.config import ChunkingConfig
from kb_api.rag_indexer.core.index.errors import index_stage
from kb_api.rag_indexer.core.scope import current_app_id


SUPPORTED_FILE_EXTENSIONS = (".pdf", ".txt", ".md", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
STABLE_CHUNK_NAMESPACE = uuid.UUID("a7c76a79-33f4-4df8-b6f8-f77553a89c11")
logger = logging.getLogger("rag_indexer")


def stable_chunk_id(app_id: str, file_id: str, chunk_index: int) -> str:
    if chunk_index < 0:
        raise ValueError("chunk_index must be greater than or equal to 0")
    file_prefix = hashlib.blake2b(f"{app_id}:{file_id}".encode("utf-8"), digest_size=12).digest()
    raw = bytearray(file_prefix + chunk_index.to_bytes(4, "big"))
    raw[6] = (raw[6] & 0x0F) | 0x50
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def index_file(state, file_id: str, presigned_url: str, filename: str, extra_metadata: dict | None = None) -> tuple[int, int | None]:
    with index_stage("parse", "parser"):
        result = state.parser_client.parse_file(presigned_url, filename=filename)
    config = getattr(getattr(state, "config", None), "chunking", ChunkingConfig())
    with index_stage("chunk", "index"):
        chunks = parser_blocks_to_chunks(result["blocks"], filename, config)
        chunks = prepare_index_chunks(chunks, app_id=current_app_id(), file_id=file_id, filename=filename, extra_metadata=extra_metadata)
    with index_stage("vector_write", "vector"):
        return state.vector_client.add_file_chunks(chunks, file_id=file_id), result.get("file_size")


def prepare_index_chunks(chunks: list[dict], *, app_id: str, file_id: str, filename: str, extra_metadata: dict | None = None) -> list[dict]:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prepared = []
    for chunk_index, chunk in enumerate(chunks):
        chunk_metadata = dict(chunk.get("metadata") or {})
        if extra_metadata:
            chunk_metadata.update(extra_metadata)
        chunk_metadata["filename"] = filename
        chunk_metadata["chunk_index"] = chunk_index
        chunk_metadata.setdefault("created_at", created_at)
        prepared.append({
            "id": stable_chunk_id(app_id, file_id, chunk_index),
            "content": chunk["content"],
            "metadata": chunk_metadata,
        })
    return prepared


def index_presigned_file(
    state,
    file_id: str,
    presigned_url: str,
    s3_url: str,
    filename: str | None = None,
    extra_metadata: dict | None = None,
) -> tuple[int, int | None]:
    """返回 ``(chunk_count, file_size)``。"""
    resolved_filename = filename or filename_from_s3_url(s3_url)
    ext = Path(resolved_filename).suffix.lower()
    validate_supported_file_extension(ext)
    metadata = {"s3_url": s3_url}
    if extra_metadata:
        metadata.update(extra_metadata)
    return index_file(state, file_id, presigned_url, resolved_filename, extra_metadata=metadata)


def validate_supported_file_extension(ext: str) -> None:
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")


def filename_from_s3_url(s3_url: str) -> str:
    _, object_name = parse_s3_url(s3_url)
    filename = Path(object_name).name
    if not filename:
        raise ValueError("filename is required when s3_url has no object name")
    return filename


def parse_s3_url(s3_url: str) -> tuple[str, str]:
    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket or not object_name:
        raise ValueError("s3_url must include bucket and object key")
    return bucket, object_name
