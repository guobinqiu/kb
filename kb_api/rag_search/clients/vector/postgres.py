from __future__ import annotations

import base64
import json
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from kb_api.rag_search.common.config import RetryConfig
from kb_api.rag_search.common.retry import retry_call
from kb_api.rag_search.core.scope import app_collection, collection_name_for_app, current_collection


_statement_timeout: ContextVar[int | None] = ContextVar("postgres_statement_timeout", default=None)
_operation_connection: ContextVar[psycopg.Connection | None] = ContextVar(
    "postgres_operation_connection", default=None,
)


def _database_operation(timeout_attribute: str, operation_name: str):
    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            token = _statement_timeout.set(getattr(self, timeout_attribute))

            def operation():
                connection_token = _operation_connection.set(None)
                try:
                    return method(self, *args, **kwargs)
                finally:
                    connection = _operation_connection.get()
                    if connection is not None:
                        connection.close()
                    _operation_connection.reset(connection_token)

            try:
                return retry_call(
                    operation,
                    self.retry,
                    should_retry=_is_retryable_database_error,
                    operation_name=operation_name,
                )
            finally:
                _statement_timeout.reset(token)
        return wrapped
    return decorate


@dataclass(frozen=True)
class MetadataFilter:
    file_ids: list[str] | None = None
    workspace_ids: list[str] | None = None


class PostgresVectorClient:
    backend_name = "postgres"

    def __init__(
        self,
        dense=None,
        bm25: bool = True,
        database_url: str | None = None,
        timeout: int | None = None,
        query_timeout: int | None = None,
        init_timeout: int | None = None,
        drop_timeout: int | None = None,
        retry: RetryConfig | None = None,
    ):
        if dense is None:
            raise ValueError("dense is required")
        if not database_url:
            raise ValueError("database_url is required")
        self.dense = dense
        self.bm25 = bm25
        self.database_url = database_url
        self.timeout = timeout
        self.query_timeout = query_timeout if query_timeout is not None else timeout
        self.init_timeout = init_timeout if init_timeout is not None else timeout
        self.drop_timeout = drop_timeout if drop_timeout is not None else timeout
        self.retry = retry or RetryConfig()
        self._ready = True

    def close(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @_database_operation("query_timeout", "postgres.list_chunks")
    def list_chunks(
        self,
        file_ids: list[str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
        workspace_ids: list[str] | None = None,
    ) -> dict:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        metadata_filter = self.build_metadata_filter(file_ids, workspace_ids)
        conditions, params = _filter_conditions(metadata_filter)
        if cursor:
            conditions.append(sql.SQL("chunk_id > %s"))
            params.append(_decode_chunk_cursor(cursor))
        query = sql.SQL("SELECT chunk_id, content, metadata FROM {}").format(
            sql.Identifier(current_collection()),
        )
        query += _where_clause(conditions)
        query += sql.SQL(" ORDER BY chunk_id ASC LIMIT %s")
        params.append(limit + 1)
        rows = self._connection().execute(query, tuple(params)).fetchall()
        page_rows = rows[:limit]
        return {
            "documents": [_row_to_document(row) for row in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1]["chunk_id"]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    def supports_sparse_vector(self) -> bool:
        return self.bm25

    @_database_operation("init_timeout", "postgres.ensure_collection")
    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        dimension = self._dense_vector_size()
        table = sql.Identifier(collection_name)
        connection = self._connection()
        connection.execute(sql.SQL(
            """CREATE TABLE IF NOT EXISTS {} (
                key_id BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                chunk_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                file_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT '',
                chunk_index BIGINT NOT NULL,
                filename TEXT NOT NULL,
                s3_url TEXT,
                metadata JSONB NOT NULL,
                embedding vector({}) NOT NULL
            )"""
        ).format(table, sql.Literal(dimension)))
        connection.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (file_id, chunk_index)").format(
            sql.Identifier(f"{collection_name}_file_chunk_idx"), table,
        ))
        connection.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops)").format(
            sql.Identifier(f"{collection_name}_embedding_idx"), table,
        ))
        if self.bm25:
            connection.execute(sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {} USING bm25 (key_id, content) WITH (key_field='key_id')"
            ).format(sql.Identifier(f"{collection_name}_bm25_idx"), table))
        return collection_name

    @_database_operation("query_timeout", "postgres.collection_exists")
    def app_collection_exists(self, app_id: str) -> bool:
        row = self._connection().execute(
            sql.SQL("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = %s
            LIMIT 1
            """),
            (collection_name_for_app(app_id),),
        ).fetchone()
        return row is not None

    @_database_operation("drop_timeout", "postgres.drop_collection")
    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        if not self.app_collection_exists(app_id):
            return False
        self._connection().execute(
            sql.SQL("DROP TABLE {}").format(sql.Identifier(collection_name))
        )
        return True

    def app_scope(self, app_id: str):
        return app_collection(app_id)

    def build_metadata_filter(
        self,
        file_ids: list[str] | None = None,
        workspace_ids: list[str] | None = None,
    ) -> MetadataFilter:
        if file_ids is not None and not file_ids:
            raise ValueError("file_ids cannot be empty")
        if workspace_ids is not None and not workspace_ids:
            raise ValueError("workspace_ids cannot be empty")
        return MetadataFilter(
            file_ids=[str(file_id) for file_id in file_ids] if file_ids is not None else None,
            workspace_ids=[str(workspace_id) for workspace_id in workspace_ids] if workspace_ids is not None else None,
        )

    def encode_dense_query(self, query: str):
        return self.dense.embed_query(query)

    @_database_operation("query_timeout", "postgres.query_dense")
    def query_dense_vector(
        self,
        query_vector,
        limit: int,
        metadata_filter: MetadataFilter | None,
    ) -> list[dict]:
        conditions, filter_params = _filter_conditions(metadata_filter)
        vector = _vector_literal(query_vector)
        query = sql.SQL(
            "SELECT chunk_id, content, metadata, "
            "1 - (embedding <=> %s::vector) AS score FROM {}"
        ).format(sql.Identifier(current_collection()))
        query += _where_clause(conditions)
        query += sql.SQL(" ORDER BY embedding <=> %s::vector LIMIT %s")
        params = [vector, *filter_params, vector, limit]
        rows = self._connection().execute(query, tuple(params)).fetchall()
        return [_row_to_item(row) for row in rows]

    def search_dense(
        self,
        query: str,
        limit: int,
        metadata_filter: MetadataFilter | None,
    ) -> list[dict]:
        return self.query_dense_vector(self.encode_dense_query(query), limit, metadata_filter)

    @_database_operation("query_timeout", "postgres.search_sparse")
    def search_sparse(
        self,
        query: str,
        limit: int,
        metadata_filter: MetadataFilter | None,
    ) -> list[dict]:
        if not self.bm25:
            raise RuntimeError("BM25 is not configured")
        conditions, filter_params = _filter_conditions(metadata_filter)
        conditions.insert(0, sql.SQL("content @@@ %s"))
        statement = sql.SQL(
            "SELECT chunk_id, content, metadata, paradedb.score(key_id) AS score FROM {}"
        ).format(sql.Identifier(current_collection()))
        statement += _where_clause(conditions)
        statement += sql.SQL(" ORDER BY score DESC LIMIT %s")
        params = [query, *filter_params, limit]
        rows = self._connection().execute(statement, tuple(params)).fetchall()
        return [_row_to_item(row) for row in rows]

    def _connection(self):
        if not self._ready:
            raise RuntimeError("search is not initialized")
        connection = _operation_connection.get()
        if connection is None:
            kwargs = {"autocommit": True, "row_factory": dict_row}
            if self.timeout is not None:
                kwargs["connect_timeout"] = self.timeout
            statement_timeout = _statement_timeout.get()
            if statement_timeout is not None:
                kwargs["options"] = f"-c statement_timeout={int(statement_timeout * 1000)}"
            connection = psycopg.connect(self.database_url, **kwargs)
            _operation_connection.set(connection)
        return connection

    def _dense_vector_size(self) -> int:
        vector_size = getattr(self.dense, "vector_size", None)
        return int(vector_size) if vector_size is not None else len(self.dense.embed_query("dimension probe"))


def _filter_conditions(metadata_filter: MetadataFilter | None):
    conditions = []
    params = []
    if metadata_filter is not None and metadata_filter.file_ids is not None:
        conditions.append(sql.SQL("file_id = ANY(%s)"))
        params.append(metadata_filter.file_ids)
    if metadata_filter is not None and metadata_filter.workspace_ids is not None:
        conditions.append(sql.SQL("workspace_id = ANY(%s)"))
        params.append(metadata_filter.workspace_ids)
    return conditions, params


def _is_retryable_database_error(exc: Exception) -> bool:
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def _where_clause(conditions: list[sql.Composable]):
    if not conditions:
        return sql.SQL("")
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)


def _vector_literal(vector) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _row_to_document(row: dict) -> dict:
    return {
        "id": str(row["chunk_id"]),
        "content": row.get("content") or "",
        "metadata": dict(row.get("metadata") or {}),
    }


def _row_to_item(row: dict) -> dict:
    item = _row_to_document(row)
    item["_score"] = float(row.get("score", 0.0))
    return item


def _encode_chunk_cursor(chunk_id: str) -> str:
    raw = json.dumps({"chunk_id": str(chunk_id)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_chunk_cursor(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(data, dict) or not isinstance(data.get("chunk_id"), str):
        raise ValueError("invalid cursor")
    return data["chunk_id"]
