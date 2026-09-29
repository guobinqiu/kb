"""Milvus-backed document storage through native pymilvus client."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from pymilvus import DataType, MilvusClient

try:
    import grpc
except ImportError:
    grpc = None

from kb_api.rag_retriever.common.config import RetryConfig
from kb_api.rag_retriever.common.contracts import Dense, Sparse
from kb_api.rag_retriever.common.retry import retry_call
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.rag_retriever.core.scope import app_collection, collection_name_for_app, current_collection


DENSE_METRIC = "COSINE"
PROJECT_ROOT = Path(__file__).resolve().parents[5]


class MilvusVectorClient:
    backend_name = "milvus"

    def __init__(
        self,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        uri: str | None = None,
        timeout: int | None = None,
        query_timeout: int | None = None,
        init_timeout: int | None = None,
        drop_timeout: int | None = None,
        token: str | None = None,
        retry: RetryConfig | None = None,
    ):
        if dense is None:
            raise ValueError("dense is required")
        self.dense = dense
        self.sparse = sparse
        self.uri = uri or "http://localhost:19530"
        self.timeout = timeout
        self.query_timeout = query_timeout if query_timeout is not None else timeout
        self.init_timeout = init_timeout if init_timeout is not None else timeout
        self.drop_timeout = drop_timeout if drop_timeout is not None else timeout
        self.token = token
        self.retry = retry or RetryConfig()
        self.client = None
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
        metadata_filter = _combine_filters(self.build_metadata_filter(file_ids, workspace_ids), _chunk_cursor_filter(cursor))
        rows = self._client().query(
            collection_name=self._chunks_collection(),
            filter=metadata_filter,
            output_fields=["*"],
            timeout=self._timeout_value(self.query_timeout),
            limit=limit + 1,
            order_by=_chunk_order_by(),
        )
        page_rows = rows[:limit]
        return {
            "documents": [_row_to_document(row) for row in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    def supports_sparse_vector(self) -> bool:
        return self.sparse is not None

    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        self.ensure_collections(collection_name)
        return collection_name

    def app_collection_exists(self, app_id: str) -> bool:
        return self._client().has_collection(collection_name_for_app(app_id))

    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        client = self._client()
        if not client.has_collection(collection_name, **self._drop_request_options()):
            return False
        client.drop_collection(collection_name, **self._drop_request_options())
        return True

    def app_scope(self, app_id: str):
        return app_collection(app_id)

    def build_metadata_filter(
        self,
        file_ids: list[str] | None = None,
        workspace_ids: list[str] | None = None,
    ) -> str:
        if file_ids is not None and not file_ids:
            raise ValueError("file_ids cannot be empty")
        if workspace_ids is not None and not workspace_ids:
            raise ValueError("workspace_ids cannot be empty")
        return _metadata_payload_filter(file_ids=file_ids, workspace_ids=workspace_ids)

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: str) -> list[dict]:
        rows = self._single_vector_search_with_data("dense", query_vector, limit, metadata_filter)
        return _documents_from_milvus_rows(rows, "dense")

    def search_dense(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    def encode_sparse_query(self, query: str):
        if self.sparse is None:
            raise RuntimeError("sparse is not configured")
        return self.sparse.embed_query(query)

    def query_sparse_vector(self, query_vector, limit: int, metadata_filter: str) -> list[dict]:
        rows = self._single_vector_search_with_data("sparse", query_vector, limit, metadata_filter)
        return _documents_from_milvus_rows(rows, "sparse")

    def search_sparse(self, query: str, limit: int, metadata_filter: str) -> list[dict]:
        return self.query_sparse_vector(self.encode_sparse_query(query), limit, metadata_filter)

    def ensure_collections(self, collection_name: str | None = None) -> None:
        client = self._client()
        target_collection = collection_name or self._chunks_collection()
        if client.has_collection(target_collection, **self._init_request_options()):
            self._ensure_dense_vector_size(target_collection)
            self._ensure_collection_compatible(target_collection)
        else:
            self._write_operation(
                lambda: client.create_collection(
                    collection_name=target_collection,
                    schema=self._collection_schema(),
                    **self._init_request_options(),
                ),
                "milvus.create_collection",
            )
            self._write_operation(
                lambda: client.create_index(
                    collection_name=target_collection,
                    index_params=self._collection_index_params(),
                    **self._init_request_options(),
                ),
                "milvus.create_index",
            )
        self._write_operation(
            lambda: client.load_collection(target_collection, **self._init_request_options()),
            "milvus.load_collection",
        )

    def _client(self):
        if self.client is None:
            self.client = MilvusClient(uri=_connection_uri(self.uri), timeout=self._timeout_value(self.query_timeout), token=self.token, dedicated=True, grpc_options={"grpc.enable_retries": 0})
        return self.client

    def _request_options(self, timeout: int | None) -> dict:
        timeout = self._timeout_value(timeout)
        # PyMilvus 3.0.1 ignores retry_times with a numeric timeout; rate-limit
        # retries can still be disabled. Schema-mismatch retries have no switch.
        return {"timeout": timeout, "retry_times": 0, "retry_on_rate_limit": False}

    def _init_request_options(self) -> dict:
        return self._request_options(self.init_timeout)

    def _drop_request_options(self) -> dict:
        return self._request_options(self.drop_timeout)

    def _timeout_value(self, timeout: int | None) -> int:
        return timeout if timeout is not None else self.timeout if self.timeout is not None else 30

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    def _collection_schema(self):
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field(field_name="pk", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="file_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="workspace_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=64, nullable=True)
        schema.add_field(field_name=self._dense_vector_field(), datatype=DataType.FLOAT_VECTOR, dim=self._dense_vector_size())
        if self.sparse is not None:
            schema.add_field(field_name=self._sparse_vector_field(), datatype=DataType.SPARSE_FLOAT_VECTOR)
        return schema

    def _collection_index_params(self):
        index_params = MilvusClient.prepare_index_params()
        for field_name, params in self._index_specs():
            index_params.add_index(field_name=field_name, **params)
        return index_params

    def _index_specs(self) -> list[tuple[str, dict]]:
        specs = [(self._dense_vector_field(), self._dense_index_params())]
        if self.sparse is not None:
            specs.append((self._sparse_vector_field(), self._sparse_index_params()))
        specs.append(("file_id", {"index_type": "INVERTED"}))
        specs.append(("chunk_index", {"index_type": "INVERTED"}))
        specs.append(("workspace_id", {"index_type": "INVERTED"}))
        return specs

    def _vector_field_for_mode(self, mode: str):
        if mode == "sparse":
            return self._sparse_vector_field()
        return "vector"

    def _dense_vector_field(self) -> str:
        return "vector"

    def _sparse_vector_field(self) -> str:
        return "sparse_vector"

    def _dense_vector_size(self) -> int:
        vector_size = getattr(self.dense, "vector_size", None)
        return int(vector_size) if vector_size is not None else len(self.dense.embed_query("dimension probe"))

    def _ensure_dense_vector_size(self, collection_name: str) -> None:
        actual_size = _dense_vector_size_from_collection(self._client().describe_collection(collection_name, **self._init_request_options()), self._dense_vector_field())
        expected_size = self._dense_vector_size()
        if actual_size is not None and actual_size != expected_size:
            raise ValueError(f"dense vector dimension mismatch: expected {expected_size}, actual {actual_size}")

    def _ensure_collection_compatible(self, collection_name: str) -> None:
        client = self._client()
        if not client.has_collection(collection_name, **self._init_request_options()):
            return
        fields = _field_names_from_collection(client.describe_collection(collection_name, **self._init_request_options()))
        if self.sparse is not None and self._sparse_vector_field() not in fields:
            raise ValueError(f"Milvus collection {collection_name} missing sparse_vector field; recreate app database after enabling sparse")

    def _search_params_for_mode(self, mode: str):
        if mode == "sparse":
            return {"metric_type": "IP", "params": {}}
        return {"metric_type": DENSE_METRIC, "params": {}}

    def _dense_index_params(self) -> dict:
        return {"metric_type": DENSE_METRIC, "index_type": "AUTOINDEX", "params": {}}

    def _sparse_index_params(self) -> dict:
        return {"metric_type": "IP", "index_type": "AUTOINDEX", "params": {}}

    def _single_vector_search_with_data(self, mode: str, query_data, limit: int, metadata_filter: str):
        self._require_ready()
        return self._client().search(
            self._chunks_collection(),
            data=[query_data],
            anns_field=self._vector_field_for_mode(mode),
            search_params=self._search_params_for_mode(mode),
            limit=limit,
            filter=metadata_filter,
            output_fields=["*"],
            timeout=self._timeout_value(self.query_timeout),
        )

    def _chunks_collection(self) -> str:
        return current_collection()


def _connection_uri(uri: str | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if uri is None or "://" in uri:
        return uri
    path = Path(uri).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _dense_vector_size_from_collection(collection: dict, field_name: str) -> int | None:
    for field in collection.get("fields", []):
        if field.get("name") != field_name:
            continue
        params = field.get("params") or {}
        dim = params.get("dim")
        return int(dim) if dim is not None else None
    return None


def _field_names_from_collection(collection: dict) -> set[str]:
    return {str(field.get("name") or field.get("field_name")) for field in collection.get("fields", [])}


def _documents_from_milvus_rows(rows, mode: str) -> list[dict]:
    if not rows:
        return []
    items = []
    for rank, row in enumerate(rows[0], start=1):
        entity = dict(row.get("entity") or {})
        metadata = _metadata_from_row(entity)
        items.append({
            "id": str(row.get("id") or entity.get("pk") or ""),
            "content": entity.get("text") or "",
            "metadata": metadata,
            "_score": _milvus_score(row.get("distance", 0.0), mode, rank),
        })
    return items


def _milvus_score(distance: float, mode: str, rank: int) -> float:
    return float(distance)


def _chunk_order_by() -> list[str]:
    return ["pk:asc"]


def _chunk_cursor_filter(cursor: str | None) -> str:
    if not cursor:
        return ""
    data = _decode_chunk_cursor(cursor)
    chunk_id = _milvus_string_literal(data["chunk_id"])
    return f"pk > {chunk_id}"


def _combine_filters(*filters: str) -> str:
    active = [metadata_filter for metadata_filter in filters if metadata_filter]
    if len(active) == 1:
        return active[0]
    return " and ".join(f"({metadata_filter})" for metadata_filter in active)


def _encode_chunk_cursor(row: dict) -> str:
    payload = {"chunk_id": str(row["pk"])}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str) -> dict:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, dict) or "chunk_id" not in data:
        raise ValueError("invalid cursor")
    return data


def _milvus_string_literal(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _row_to_document(row: dict) -> dict:
    metadata = _metadata_from_row(row)
    return {
        "id": str(row.get("pk") or metadata.get("id", "")),
        "content": row.get("text") or "",
        "metadata": metadata,
    }


def _metadata_payload_filter(
    file_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
) -> str:
    filters = []
    if file_ids is not None:
        filters.append(f"file_id in {[str(file_id) for file_id in file_ids]!r}")
    if workspace_ids is not None:
        filters.append(f"workspace_id in {[str(workspace_id) for workspace_id in workspace_ids]!r}")
    return " and ".join(filters)


def _metadata_from_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"pk", "text", "vector"}
    }


def _retryable_vector_error(exc: Exception) -> bool:
    if isinstance(exc, UpstreamServiceError):
        return exc.retryable
    if grpc is not None and isinstance(exc, grpc.RpcError):
        return exc.code() in {
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.UNAVAILABLE,
        }
    code = getattr(exc, "code", None)
    code_name = getattr(code, "name", None) or str(code)
    return code_name.upper() in {"DEADLINE_EXCEEDED", "UNAVAILABLE"}
