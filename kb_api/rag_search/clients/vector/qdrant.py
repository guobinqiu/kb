"""Qdrant-backed document storage and collection management."""
from __future__ import annotations

import base64
import json
import math

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from kb_api.rag_search.common.config import QdrantQuantizationConfig, RetryConfig
from kb_api.rag_search.common.contracts import Dense
from kb_api.rag_search.common.retry import retry_call
from kb_api.rag_search.common.upstream import UpstreamServiceError
from kb_api.rag_search.core.scope import app_collection, collection_name_for_app, current_collection


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
        self.init_timeout = init_timeout if init_timeout is not None else timeout
        self.drop_timeout = drop_timeout if drop_timeout is not None else timeout
        self.quantization = quantization
        self.api_key = api_key
        self.retry = retry or RetryConfig()
        self.client: QdrantClient | None = None
        self._ready = True

    def close(self) -> None:
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if callable(close):
                close()
        self.client = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def _write_operation(self, operation, operation_name: str):
        try:
            return retry_call(operation, self.retry, should_retry=_retryable_vector_error, operation_name=operation_name)
        except Exception as exc:
            if _retryable_vector_error(exc):
                raise UpstreamServiceError(service="vector", error=str(exc) or None, retryable=True, status_code=503) from exc
            raise

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None, workspace_ids: list[str] | None = None) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        try:
            rows, next_offset = self._client().scroll(
                collection_name=self._chunks_collection(),
                scroll_filter=self.build_metadata_filter(file_ids, workspace_ids),
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
        return math.ceil(self._timeout_value(timeout))

    def _query_timeout(self) -> int:
        return self._operation_timeout(self.query_timeout)

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
