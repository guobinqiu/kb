"""PostgreSQL-backed document storage for App-scoped chunk tables."""
from __future__ import annotations

import base64
import json
import re
from contextvars import ContextVar
from functools import wraps

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from kb_api.rag_indexer.common.config import RetryConfig
from kb_api.rag_indexer.common.contracts import Dense
from kb_api.rag_indexer.common.retry import retry_call
from kb_api.rag_indexer.core.scope import app_collection, collection_name_for_app, current_collection


_statement_timeout: ContextVar[int | None] = ContextVar("postgres_statement_timeout", default=None)


def _database_operation(timeout_attribute: str, operation_name: str):
    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            token = _statement_timeout.set(getattr(self, timeout_attribute))
            try:
                return retry_call(
                    lambda: method(self, *args, **kwargs),
                    self.retry,
                    should_retry=_is_retryable_database_error,
                    operation_name=operation_name,
                )
            finally:
                _statement_timeout.reset(token)
        return wrapped
    return decorate


class PostgresVectorClient:
    backend_name = "postgres"

    def __init__(
        self,
        dense: Dense | None = None,
        bm25: bool = True,
        database_url: str | None = None,
        timeout: int | None = None,
        query_timeout: int | None = None,
        write_timeout: int | None = None,
        init_timeout: int | None = None,
        drop_timeout: int | None = None,
        retry: RetryConfig | None = None,
        **_kwargs,
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
        self.write_timeout = write_timeout if write_timeout is not None else timeout
        self.init_timeout = init_timeout if init_timeout is not None else timeout
        self.drop_timeout = drop_timeout if drop_timeout is not None else timeout
        self.retry = retry or RetryConfig()
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        self._ready = True

    def close(self) -> None:
        self._ready = False

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
        except Exception:
            return False

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        if not file_id:
            raise ValueError("file_id is required")
        self._require_ready()
        rows = self._to_rows(chunks, file_id)
        return self._write_file_chunks(rows, file_id, len(chunks))

    @_database_operation("write_timeout", "postgres.add_chunks")
    def _write_file_chunks(self, rows: list[tuple], file_id: str, chunk_count: int) -> int:
        table = self._table(current_collection())
        upsert = sql.SQL(
            """INSERT INTO {} (chunk_id, content, file_id, workspace_id, chunk_index, filename, s3_url, metadata, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (chunk_id) DO UPDATE SET
                content = EXCLUDED.content,
                file_id = EXCLUDED.file_id,
                workspace_id = EXCLUDED.workspace_id,
                chunk_index = EXCLUDED.chunk_index,
                filename = EXCLUDED.filename,
                s3_url = EXCLUDED.s3_url,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding"""
        ).format(table)
        delete_stale = sql.SQL("DELETE FROM {} WHERE file_id = %s AND chunk_index >= %s").format(table)
        with self._connect() as connection, connection.cursor() as cursor:
            if rows:
                cursor.executemany(upsert, rows)
            cursor.execute(delete_stale, (file_id, chunk_count))
        return chunk_count

    def delete_file_chunks(self, file_id: str) -> int:
        return self._delete(sql.SQL("file_id = %s"), (file_id,))

    def delete_stale_file_chunks(self, file_id: str, keep_count: int) -> int:
        return self._delete(sql.SQL("file_id = %s AND chunk_index >= %s"), (file_id, int(keep_count)))

    @_database_operation("query_timeout", "postgres.count_chunks")
    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        self._require_ready()
        query = sql.SQL("SELECT COUNT(*) FROM {}").format(self._table(current_collection()))
        params = None
        if file_ids is not None:
            if not file_ids:
                raise ValueError("file_ids cannot be empty")
            query += sql.SQL(" WHERE file_id = ANY(%s)")
            params = (file_ids,)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    @_database_operation("query_timeout", "postgres.list_chunks")
    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        self._require_ready()
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        conditions = []
        params = []
        if file_ids is not None:
            if not file_ids:
                raise ValueError("file_ids cannot be empty")
            conditions.append(sql.SQL("file_id = ANY(%s)"))
            params.append(file_ids)
        if cursor:
            conditions.append(sql.SQL("chunk_id > %s"))
            params.append(_decode_chunk_cursor(cursor))
        query = sql.SQL("SELECT chunk_id, content, metadata FROM {}").format(self._table(current_collection()))
        if conditions:
            query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        query += sql.SQL(" ORDER BY chunk_id ASC LIMIT %s")
        params.append(limit + 1)
        with self._connect() as connection, connection.cursor() as db_cursor:
            db_cursor.execute(query, tuple(params))
            rows = db_cursor.fetchall()
        page_rows = rows[:limit]
        return {
            "documents": [_row_to_document(row) for row in page_rows],
            "next_cursor": _encode_chunk_cursor(page_rows[-1][0]) if len(rows) > limit and page_rows else None,
            "has_more": len(rows) > limit,
        }

    @_database_operation("query_timeout", "postgres.get_dense_vector")
    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        self._require_ready()
        query = sql.SQL("SELECT embedding FROM {} WHERE chunk_id = %s").format(self._table(current_collection()))
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (chunk_id,))
            row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        return _vector_from_database(row[0])

    def supports_dense_vector(self) -> bool:
        return True

    def supports_sparse_vector(self) -> bool:
        return self.bm25

    @_database_operation("init_timeout", "postgres.ensure_collection")
    def ensure_app_collection(self, app_id: str) -> str:
        collection_name = collection_name_for_app(app_id)
        dimension = self._dense_vector_size()
        table = self._table(collection_name)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT format_type(attribute.atttypid, attribute.atttypmod)
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = current_schema()
                  AND relation.relname = %s
                  AND attribute.attname = 'embedding'
                  AND NOT attribute.attisdropped""",
                (collection_name,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                actual_dimension = _vector_dimension(row[0])
                if actual_dimension != dimension:
                    raise ValueError(
                        f"dense vector dimension mismatch: expected {dimension}, actual {actual_dimension}"
                    )
            cursor.execute(sql.SQL(
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
            cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (file_id, chunk_index)").format(
                sql.Identifier(f"{collection_name}_file_chunk_idx"), table,
            ))
            cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops)").format(
                sql.Identifier(f"{collection_name}_embedding_idx"), table,
            ))
            if self.bm25:
                cursor.execute(sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {} ON {} USING bm25 (key_id, content) WITH (key_field='key_id')"
                ).format(sql.Identifier(f"{collection_name}_bm25_idx"), table))
        return collection_name

    @_database_operation("query_timeout", "postgres.collection_exists")
    def app_collection_exists(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = %s""",
                (collection_name,),
            )
            row = cursor.fetchone()
        return bool(row and row[0])

    @_database_operation("drop_timeout", "postgres.drop_collection")
    def drop_app_collection(self, app_id: str) -> bool:
        collection_name = collection_name_for_app(app_id)
        if not self.app_collection_exists(app_id):
            return False
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(self._table(collection_name)))
        return True

    @_database_operation("drop_timeout", "postgres.drop_collections")
    def drop_collections(self) -> None:
        self._require_ready()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(self._table(current_collection())))

    def app_scope(self, app_id: str):
        return app_collection(app_id)

    @_database_operation("write_timeout", "postgres.delete_chunks")
    def _delete(self, where: sql.Composable, params: tuple) -> int:
        self._require_ready()
        collection_name = current_collection()
        query = sql.SQL("DELETE FROM {} WHERE ").format(self._table(collection_name)) + where
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = %s""",
                (collection_name,),
            )
            if cursor.fetchone() is None:
                return 0
            cursor.execute(query, params)
            return max(int(cursor.rowcount), 0)

    def _to_rows(self, chunks: list[dict], file_id: str) -> list[tuple]:
        if not chunks:
            return []
        contents = [chunk["content"] for chunk in chunks]
        vectors = self.dense.embed_documents(contents)
        expected_dimension = self._dense_vector_size()
        rows = []
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != expected_dimension:
                raise ValueError(
                    f"dense vector dimension mismatch: expected {expected_dimension}, actual {len(vector)}"
                )
            metadata = dict(chunk.get("metadata") or {})
            metadata["file_id"] = file_id
            if "chunk_index" not in metadata:
                raise ValueError("chunk metadata.chunk_index is required")
            if not metadata.get("filename"):
                raise ValueError("chunk metadata.filename is required")
            rows.append((
                str(chunk["id"]),
                chunk["content"],
                file_id,
                str(metadata.get("workspace_id") or ""),
                int(metadata["chunk_index"]),
                metadata["filename"],
                metadata.get("s3_url"),
                Jsonb(metadata),
                _vector_literal(vector),
            ))
        return rows

    def _dense_vector_size(self) -> int:
        vector_size = getattr(self.dense, "vector_size", None)
        return int(vector_size) if vector_size is not None else len(self.dense.embed_query("dimension probe"))

    def _connect(self):
        kwargs = {}
        if self.timeout is not None:
            kwargs["connect_timeout"] = self.timeout
        statement_timeout = _statement_timeout.get()
        if statement_timeout is not None:
            kwargs["options"] = f"-c statement_timeout={int(statement_timeout * 1000)}"
        return psycopg.connect(self.database_url, **kwargs)

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("search is not initialized")

    @staticmethod
    def _table(collection_name: str) -> sql.Composed:
        return sql.Identifier(collection_name)


def _vector_dimension(type_name: str) -> int:
    match = re.fullmatch(r"vector\((\d+)\)", str(type_name))
    if not match:
        raise ValueError(f"invalid PostgreSQL vector type: {type_name}")
    return int(match.group(1))


def _is_retryable_database_error(exc: Exception) -> bool:
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def _vector_literal(vector) -> str:
    return json.dumps([float(value) for value in vector], separators=(",", ":"))


def _vector_from_database(value) -> list[float]:
    if isinstance(value, str):
        value = json.loads(value)
    return [float(item) for item in value]


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


def _row_to_document(row) -> dict:
    return {
        "id": str(row[0]),
        "content": row[1] or "",
        "metadata": dict(row[2] or {}),
    }
