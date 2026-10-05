"""Qdrant-backed document storage and collection management."""
from __future__ import annotations

import base64
import json
import logging
import math
import threading
import time

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from kb_api.rag_indexer.common.config import QdrantQuantizationConfig, RetryConfig
from kb_api.rag_indexer.common.contracts import Dense
from kb_api.rag_indexer.common.deadline import check_deadline, request_timeout
from kb_api.rag_indexer.common.retry import retry_call
from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from kb_api.rag_indexer.core.scope import app_collection, collection_name_for_app, current_app_id, current_collection
import httpx
from qdrant_client.http.exceptions import ResponseHandlingException


logger = logging.getLogger("kb_api.rag_indexer.core.indexing")


class QdrantVectorClient:
    backend_name = "qdrant"

    def __init__(
        self,
        dense: Dense | None = None,
        bm25: bool = False,
        url: str | None = None,
        timeout: int | None = None,
        quantization: QdrantQuantizationConfig | None = None,
        api_key: str | None = None,
        retry: RetryConfig | None = None,
        query_timeout: int | None = None,
        write_timeout: int | None = None,
        init_timeout: int | None = None,
        drop_timeout: int | None = None,
    ):
        if dense is None:
            raise ValueError("dense is required")
        self.dense = dense
        self.bm25 = bm25
        self.url = url or "http://localhost:6333"
        self.timeout = timeout
        self.query_timeout = query_timeout if query_timeout is not None else timeout
        self.write_timeout = write_timeout if write_timeout is not None else timeout
        self.init_timeout = init_timeout if init_timeout is not None else timeout
        self.drop_timeout = drop_timeout if drop_timeout is not None else timeout
        self.quantization = quantization
        self.api_key = api_key
        self.retry = retry or RetryConfig()
        self.client: QdrantClient | None = None
        self.dense_vector_size: int | None = None
        self._document_locks: dict[str, threading.Lock] = {}
        self._document_locks_guard = threading.Lock()
        self._ready = True

    def start(self) -> None:
        self._ready = True

    def close(self) -> None:
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if callable(close):
                close()
        self.client = None
        self._ready = False

    def stop(self) -> None:
        self.close()

    def drop_collections(self) -> None:
        collection_name = self._chunks_collection()
        client = self._client()
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name, timeout=self._drop_timeout())

    @property
    def ready(self) -> bool:
        return self._ready

    def ping(self) -> bool:
        try:
            self._client().get_collections()
            return True
        except Exception:
            return False

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        if not file_id:
            raise ValueError("file_id is required")
        self._require_ready()
        with self._document_lock(file_id):
            check_deadline()
            app_id = current_app_id()
            points = self._to_points(chunks, file_id) if chunks else []
            if points:
                started = time.perf_counter()
                logger.info("Qdrant upsert start", extra={"event": "qdrant_upsert_start", "stage": "index", "backend": "qdrant", "retriever": "vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(chunks), "point_count": len(points)})
                check_deadline()
                self._write_operation(
                    lambda: self._client().upsert(
                        collection_name=self._chunks_collection(),
                        points=points,
                        timeout=self._write_timeout(),
                    ),
                    "qdrant.upsert",
                )
                total_ms = round((time.perf_counter() - started) * 1000, 1)
                logger.info("Qdrant upsert done", extra={"event": "qdrant_upsert_done", "stage": "index", "backend": "qdrant", "retriever": "vector", "app_id": app_id, "file_id": file_id, "chunk_count": len(chunks), "point_count": len(points), "total_ms": total_ms, "status": "ok"})
            check_deadline()
            self.delete_stale_file_chunks(file_id, len(chunks))
            check_deadline()
        return len(chunks)

    def delete_file_chunks(self, file_id: str) -> int:
        return self._delete_by_filter(_file_payload_filter(file_ids=[file_id]))

    def delete_stale_file_chunks(self, file_id: str, keep_count: int) -> int:
        metadata_filter = _stale_file_payload_filter(file_id, keep_count)
        check_deadline()
        before = int(self._write_operation(
            lambda: self._client().count(collection_name=self._chunks_collection(), count_filter=metadata_filter, exact=True, timeout=self._write_timeout()),
            "qdrant.count",
        ).count)
        if before:
            check_deadline()
            self._write_operation(
                lambda: self._client().delete(collection_name=self._chunks_collection(), points_selector=models.FilterSelector(filter=metadata_filter), timeout=self._write_timeout()),
                "qdrant.delete",
            )
        return before

    def _write_operation(self, operation, operation_name: str):
        try:
            return retry_call(operation, self.retry, should_retry=_retryable_vector_error, operation_name=operation_name)
        except Exception as exc:
            if _retryable_vector_error(exc):
                raise UpstreamServiceError(service="vector", error=str(exc) or None, retryable=True, status_code=503) from exc
            raise

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        return self._count_documents(self.build_file_filter(file_ids))

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        try:
            rows, next_offset = self._client().scroll(
                collection_name=self._chunks_collection(),
                scroll_filter=self.build_file_filter(file_ids),
                limit=limit,
                offset=_decode_chunk_cursor(cursor) if cursor else None,
                with_payload=True,
                with_vectors=False,
                timeout=self._query_timeout(),
            )
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return {"documents": [], "next_cursor": None, "has_more": False}
            raise
        page_rows = [_record_to_document(row) for row in rows]
        return {
            "documents": page_rows,
            "next_cursor": _encode_chunk_cursor(next_offset) if next_offset is not None else None,
            "has_more": next_offset is not None,
        }

    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        vectors = self._get_point_vectors(chunk_id)
        if vectors is None:
            return None
        dense = vectors.get("dense") if isinstance(vectors, dict) else vectors
        return list(dense) if dense is not None else None

    def supports_dense_vector(self) -> bool:
        return True

    def supports_sparse_vector(self) -> bool:
        return self.bm25

    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        self.ensure_collections(collection_name)
        return collection_name

    def app_collection_exists(self, app_id: str) -> bool:
        return self._client().collection_exists(collection_name_for_app(app_id))

    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        client = self._client()
        if not client.collection_exists(collection_name):
            return False
        client.delete_collection(collection_name, timeout=self._drop_timeout())
        return True

    def app_scope(self, app_id: str):
        return app_collection(app_id)

    def build_file_filter(self, file_ids: list[str] | None = None) -> models.Filter | None:
        if file_ids is None:
            return None
        if not file_ids:
            raise ValueError("file_ids cannot be empty")
        return _file_payload_filter(file_ids=file_ids)

    def build_metadata_filter(
        self,
        file_ids: list[str] | None = None,
        workspace_ids: list[str] | None = None,
    ) -> models.Filter | None:
        if file_ids is not None and not file_ids:
            raise ValueError("file_ids cannot be empty")
        if workspace_ids is not None and not workspace_ids:
            raise ValueError("workspace_ids cannot be empty")
        return _metadata_payload_filter(file_ids=file_ids, workspace_ids=workspace_ids)

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self._query_points(query_vector, "dense", limit, metadata_filter)

    def search_dense(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    def search_sparse(self, query: str, limit: int, metadata_filter: models.Filter) -> list[dict]:
        if not self.bm25:
            raise RuntimeError("BM25 is not configured")
        return self._query_points(_bm25_document(query), "bm25", limit, metadata_filter)

    def ensure_collections(self, collection_name: str | None = None) -> None:
        client = self._client()
        dense_size = self._get_dense_vector_size()
        target_collection = collection_name or self._chunks_collection()
        if client.collection_exists(target_collection):
            self._ensure_dense_vector_size(target_collection, dense_size)
            self._ensure_bm25_vector(target_collection)
            self.ensure_payload_indexes(target_collection)
            return
        self._write_operation(
            lambda: client.create_collection(
                collection_name=target_collection,
                vectors_config={
                    "dense": models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
                },
                sparse_vectors_config=_qdrant_bm25_config(self.bm25),
                quantization_config=_quantization_config(self.quantization),
                timeout=self._init_timeout(),
            ),
            "qdrant.create_collection",
        )
        _wait_collection_ready(client, target_collection, timeout=self._init_timeout())
        self.ensure_payload_indexes(target_collection)

    def ensure_payload_indexes(self, collection_name: str | None = None) -> None:
        client = self._client()
        target_collection = collection_name or self._chunks_collection()
        self._write_operation(
            lambda: _ensure_payload_index(client, target_collection, "metadata.file_id", models.PayloadSchemaType.KEYWORD, timeout=self._init_timeout()),
            "qdrant.create_payload_index",
        )
        self._write_operation(
            lambda: _ensure_payload_index(client, target_collection, "metadata.chunk_index", models.PayloadSchemaType.INTEGER, timeout=self._init_timeout()),
            "qdrant.create_payload_index",
        )
        self._write_operation(
            lambda: _ensure_payload_index(client, target_collection, "metadata.workspace_id", models.PayloadSchemaType.KEYWORD, timeout=self._init_timeout()),
            "qdrant.create_payload_index",
        )

    def _client(self) -> QdrantClient:
        if self.client is None:
            self.client = QdrantClient(url=self.url, timeout=self._timeout_value(self.query_timeout), check_compatibility=False, api_key=self.api_key, cloud_inference=self.bm25)
        return self.client

    def _operation_timeout(self, timeout: int | None) -> int:
        timeout = request_timeout(self._timeout_value(timeout))
        # Qdrant REST converts timeout to integer seconds. Avoid truncating a
        # positive subsecond budget to zero; the next stage checks the deadline.
        return math.ceil(timeout)

    def _query_timeout(self) -> int:
        return self._operation_timeout(self.query_timeout)

    def _write_timeout(self) -> int:
        return self._operation_timeout(self.write_timeout)

    def _init_timeout(self) -> int:
        return self._operation_timeout(self.init_timeout)

    def _drop_timeout(self) -> int:
        return self._operation_timeout(self.drop_timeout)

    def _timeout_value(self, timeout: int | None) -> int:
        return timeout if timeout is not None else self.timeout if self.timeout is not None else 30

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    def _get_dense_vector_size(self) -> int:
        vector_size = getattr(self.dense, "vector_size", None)
        return int(vector_size) if vector_size is not None else len(self.dense.embed_query("dimension probe"))

    def _ensure_dense_vector_size(self, collection_name: str, expected_size: int) -> None:
        actual_size = _dense_vector_size_from_collection(self._client().get_collection(collection_name))
        if actual_size is not None and actual_size != expected_size:
            raise ValueError(f"dense vector dimension mismatch: expected {expected_size}, actual {actual_size}")

    def _ensure_bm25_vector(self, collection_name: str) -> None:
        if not self.bm25:
            return
        params = self._client().get_collection(collection_name).config.params
        sparse_vectors = getattr(params, "sparse_vectors", None) or {}
        if "bm25" not in sparse_vectors or sparse_vectors["bm25"].modifier != models.Modifier.IDF:
            raise ValueError(f"Qdrant collection {collection_name} has no BM25 vector; recreate the collection before enabling BM25")

    def _chunks_collection(self) -> str:
        return current_collection()

    def _document_lock(self, file_id: str):
        with self._document_locks_guard:
            lock = self._document_locks.get(file_id)
            if lock is None:
                lock = threading.Lock()
                self._document_locks[file_id] = lock
            return lock

    def _query_points(self, query, vector_name: str, limit: int, metadata_filter: models.Filter | None) -> list[dict]:
        self._require_ready()
        try:
            response = self._client().query_points(
                collection_name=self._chunks_collection(),
                query=query,
                using=vector_name,
                query_filter=metadata_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
                timeout=self._query_timeout(),
            )
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return []
            raise
        return [_point_to_item(point) for point in response.points]

    def _get_point_vectors(self, chunk_id: str):
        self._require_ready()
        rows = self._client().retrieve(
            collection_name=self._chunks_collection(),
            ids=[_point_id(chunk_id)],
            with_payload=False,
            with_vectors=True,
            timeout=self._query_timeout(),
        )
        if not rows:
            return None
        return getattr(rows[0], "vector", None)

    def _delete_by_filter(self, metadata_filter: models.Filter) -> int:
        before = self._count_documents(metadata_filter)
        if before:
            try:
                self._client().delete(collection_name=self._chunks_collection(), points_selector=models.FilterSelector(filter=metadata_filter), timeout=self._write_timeout())
            except UnexpectedResponse as exc:
                if _is_collection_not_found(exc):
                    return 0
                raise
        return before

    def _count_documents(self, metadata_filter: models.Filter | None) -> int:
        try:
            result = self._client().count(collection_name=self._chunks_collection(), count_filter=metadata_filter, exact=True, timeout=self._query_timeout())
        except UnexpectedResponse as exc:
            if _is_collection_not_found(exc):
                return 0
            raise
        return int(result.count)

    def _to_points(self, chunks: list[dict], file_id: str) -> list[models.PointStruct]:
        app_id = current_app_id()
        contents = [chunk["content"] for chunk in chunks]
        dense_vectors = self._dense_vectors_for_documents(contents, file_id, app_id)
        points = []
        for index, (chunk, dense_vector) in enumerate(zip(chunks, dense_vectors)):
            point_id = _point_id(chunk["id"])
            vector = {"dense": dense_vector}
            if self.bm25:
                vector["bm25"] = _bm25_document(contents[index])
            points.append(models.PointStruct(id=point_id, vector=vector, payload=_payload_for_chunk(chunk, file_id)))
        return points

    def _dense_vectors_for_documents(self, contents: list[str], file_id: str, app_id: str) -> list[list[float]]:
        started = time.perf_counter()
        logger.info("Dense embedding start", extra={"event": "dense_embedding_start", "stage": "embedding", "backend": "model", "retriever": "dense", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents)})
        dense_vectors = self.dense.embed_documents(contents)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Dense embedding done", extra={"event": "dense_embedding_done", "stage": "embedding", "backend": "model", "retriever": "dense", "app_id": app_id, "file_id": file_id, "chunk_count": len(contents), "total_ms": total_ms, "status": "ok"})
        return dense_vectors

def _wait_collection_ready(client: QdrantClient, collection_name: str, timeout: int = 30) -> None:
    client.get_collection(collection_name)
    client.count(collection_name=collection_name, exact=True, timeout=timeout)


def _ensure_payload_index(client: QdrantClient, collection_name: str, field_name: str, field_schema: models.PayloadSchemaType, timeout: int):
    client.create_payload_index(
        collection_name=collection_name,
        field_name=field_name,
        field_schema=field_schema,
        timeout=timeout,
    )


def _quantization_config(config: QdrantQuantizationConfig | None):
    if config is None or not config.enable:
        return None
    if config.type != "int8":
        raise ValueError("qdrant quantization.type only supports int8")
    scalar = models.ScalarQuantizationConfig(type=models.ScalarType.INT8)
    if config.quantile is not None:
        scalar.quantile = config.quantile
    if config.always_ram is not None:
        scalar.always_ram = config.always_ram
    return models.ScalarQuantization(scalar=scalar)


def _qdrant_bm25_config(bm25: bool):
    if not bm25:
        return None
    return {"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)}


def _bm25_document(text: str) -> models.Document:
    return models.Document(
        text=text, model="qdrant/bm25",
        options={"tokenizer": "multilingual", "stemmer": {"type": "none"}, "stopwords": {}},
    )


def _dense_vector_size_from_collection(collection_info) -> int | None:
    vectors = getattr(getattr(getattr(collection_info, "config", None), "params", None), "vectors", None)
    if isinstance(vectors, dict):
        dense = vectors.get("dense")
        return getattr(dense, "size", None)
    return getattr(vectors, "size", None)


def _retryable_vector_error(exc: Exception) -> bool:
    if isinstance(exc, UpstreamServiceError):
        return exc.retryable

    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, ResponseHandlingException)):
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and 500 <= status_code < 600


def _file_payload_filter(file_ids: list[str]) -> models.Filter:
    return _metadata_payload_filter(file_ids=file_ids)


def _metadata_payload_filter(
    file_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
) -> models.Filter | None:
    must = []
    if file_ids is not None:
        must.append(models.FieldCondition(key="metadata.file_id", match=models.MatchAny(any=file_ids)))
    if workspace_ids is not None:
        must.append(models.FieldCondition(key="metadata.workspace_id", match=models.MatchAny(any=workspace_ids)))
    return models.Filter(must=must) if must else None


def _stale_file_payload_filter(file_id: str, keep_count: int) -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="metadata.file_id", match=models.MatchValue(value=file_id)),
        models.FieldCondition(key="metadata.chunk_index", range=models.Range(gte=keep_count)),
    ])


def _combine_chunk_filters(*filters: models.Filter | None) -> models.Filter | None:
    active = [metadata_filter for metadata_filter in filters if metadata_filter is not None]
    if not active:
        return None
    must = []
    for metadata_filter in active:
        must.extend(metadata_filter.must or [])
    return models.Filter(must=must)


def _encode_chunk_cursor(offset) -> str:
    data = {"offset": offset}
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str):
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, dict) or "offset" not in data:
        raise ValueError("invalid cursor")
    return data["offset"]


def _record_to_document(row) -> dict:
    payload = row.payload or {}
    metadata = _metadata_from_payload(payload)
    content = payload.get("page_content") or payload.get("content") or ""
    return {
        "id": str(row.id),
        "content": content,
        "metadata": metadata,
    }


def _payload_for_chunk(chunk: dict, file_id: str) -> dict:
    metadata = dict(chunk.get("metadata") or {})
    metadata["file_id"] = file_id
    if "chunk_index" not in metadata:
        raise ValueError("chunk metadata.chunk_index is required")
    if not metadata.get("filename"):
        raise ValueError("chunk metadata.filename is required")
    return {
        "content": chunk["content"],
        "metadata": metadata,
    }


def _is_collection_not_found(exc: UnexpectedResponse) -> bool:
    return getattr(exc, "status_code", None) == 404 or "Collection" in str(exc) and "doesn't exist" in str(exc)


def _point_to_item(point) -> dict:
    payload = dict(point.payload or {})
    return {
        "id": str(point.id),
        "content": payload.get("content") or payload.get("page_content") or "",
        "metadata": _metadata_from_payload(payload),
        "_score": float(point.score),
    }


def _metadata_from_payload(payload: dict | None) -> dict:
    if not payload:
        return {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return payload


def _point_id(chunk_id: str) -> str:
    return chunk_id
