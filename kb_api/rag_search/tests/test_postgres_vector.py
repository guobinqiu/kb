from __future__ import annotations

import pytest
import psycopg
from psycopg import sql

from kb_api.rag_search.clients.vector import postgres
from kb_api.rag_search.clients.vector.postgres import PostgresVectorClient
from kb_api.rag_search.common.config import RetryConfig
from kb_api.rag_search.core.scope import current_collection


class Dense:
    vector_size = 3

    def embed_query(self, query: str):
        assert query == "arrival service"
        return [0.1, 0.2, 0.3]


class Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return Result(self.responses.pop(0) if self.responses else [])

    def close(self):
        self.closed = True


def _client(monkeypatch, connection, *, bm25=True):
    monkeypatch.setattr(postgres.psycopg, "connect", lambda *args, **kwargs: connection)
    return PostgresVectorClient(
        dense=Dense(),
        bm25=bm25,
        database_url="postgresql://rag:secret@db/rag",
    )


def _query_text(query) -> str:
    assert isinstance(query, sql.Composable)
    return query.as_string()


def test_lifecycle_uses_app_table_identifiers_and_closes_connection(monkeypatch):
    connection = Connection([{"exists": True}], [{"exists": True}], [])
    vector = _client(monkeypatch, connection)

    assert vector.backend_name == "postgres"
    assert vector.ready is True
    assert vector.app_collection_exists("acme") is True
    assert vector.drop_app_collection("acme") is True

    exists_sql = _query_text(connection.calls[0][0])
    drop_sql = _query_text(connection.calls[2][0])
    assert "information_schema.tables" in exists_sql
    assert connection.calls[0][1] == ("acme_chunks",)
    assert drop_sql == 'DROP TABLE "acme_chunks"'

    vector.close()
    assert connection.closed is True
    assert vector.ready is False


def test_app_scope_routes_current_collection():
    vector = PostgresVectorClient(dense=Dense(), database_url="postgresql://db/rag")

    with vector.app_scope("tenant_a"):
        assert current_collection() == "tenant_a_chunks"


def test_ensure_app_collection_creates_dense_and_bm25_indexes(monkeypatch):
    connection = Connection([], [], [], [])
    vector = _client(monkeypatch, connection)

    assert vector.ensure_app_collection("acme") == "acme_chunks"

    statements = [_query_text(query) for query, _ in connection.calls]
    assert 'CREATE TABLE IF NOT EXISTS "acme_chunks"' in statements[0]
    assert "embedding vector(3) NOT NULL" in statements[0]
    assert any("USING hnsw" in statement for statement in statements)
    assert any("USING bm25 (key_id, content)" in statement for statement in statements)


def test_metadata_filters_reject_empty_lists_and_keep_values_as_parameters(monkeypatch):
    connection = Connection([])
    vector = _client(monkeypatch, connection)

    with pytest.raises(ValueError, match="file_ids"):
        vector.build_metadata_filter(file_ids=[])
    with pytest.raises(ValueError, match="workspace_ids"):
        vector.build_metadata_filter(workspace_ids=[])

    metadata_filter = vector.build_metadata_filter(
        file_ids=["file-a' OR TRUE --"],
        workspace_ids=["workspace-a"],
    )
    with vector.app_scope("acme"):
        vector.query_dense_vector([0.1, 0.2, 0.3], 5, metadata_filter)

    query, params = connection.calls[0]
    query_text = _query_text(query)
    assert "file-a' OR TRUE --" not in query_text
    assert "file_id = ANY(%s)" in query_text
    assert "workspace_id = ANY(%s)" in query_text
    assert ["file-a' OR TRUE --"] in params
    assert ["workspace-a"] in params


def test_dense_search_uses_cosine_distance_and_returns_public_item_shape(monkeypatch):
    connection = Connection([{
        "chunk_id": "chunk-1",
        "content": "airport pickup",
        "metadata": {"file_id": "file-a", "workspace_id": "workspace-a"},
        "score": 0.75,
    }])
    vector = _client(monkeypatch, connection)

    with vector.app_scope("acme"):
        items = vector.search_dense("arrival service", 3, None)

    query, params = connection.calls[0]
    query_text = _query_text(query)
    assert 'FROM "acme_chunks"' in query_text
    assert "1 - (embedding <=> %s::vector) AS score" in query_text
    assert "ORDER BY embedding <=> %s::vector" in query_text
    assert params == ("[0.1,0.2,0.3]", "[0.1,0.2,0.3]", 3)
    assert items == [{
        "id": "chunk-1",
        "content": "airport pickup",
        "metadata": {"file_id": "file-a", "workspace_id": "workspace-a"},
        "_score": 0.75,
    }]


def test_bm25_search_uses_paradedb_score_and_parameterizes_query(monkeypatch):
    connection = Connection([{
        "chunk_id": "chunk-2",
        "content": "hotel transfer",
        "metadata": {},
        "score": 9.5,
    }])
    vector = _client(monkeypatch, connection)
    query_text = "hotel') OR TRUE --"

    with vector.app_scope("acme"):
        items = vector.search_sparse(query_text, 4, None)

    query, params = connection.calls[0]
    rendered = _query_text(query)
    assert "paradedb.score(key_id) AS score" in rendered
    assert "WHERE content @@@ %s" in rendered
    assert "ORDER BY score DESC" in rendered
    assert query_text not in rendered
    assert params == (query_text, 4)
    assert items[0]["_score"] == 9.5


def test_bm25_can_be_disabled_without_disabling_dense_search(monkeypatch):
    vector = _client(monkeypatch, Connection([]), bm25=False)

    assert vector.supports_sparse_vector() is False
    with vector.app_scope("acme"):
        with pytest.raises(RuntimeError, match="BM25"):
            vector.search_sparse("hotel", 4, None)


def test_chunk_listing_uses_keyset_cursor_and_metadata_filters(monkeypatch):
    first_page = [
        {"chunk_id": "chunk-1", "content": "one", "metadata": {"file_id": "file-a"}},
        {"chunk_id": "chunk-2", "content": "two", "metadata": {"file_id": "file-a"}},
        {"chunk_id": "chunk-3", "content": "three", "metadata": {"file_id": "file-a"}},
    ]
    first_connection = Connection(first_page)
    vector = _client(monkeypatch, first_connection)

    with vector.app_scope("acme"):
        page = vector.list_chunks(file_ids=["file-a"], workspace_ids=["workspace-a"], limit=2)

    assert [item["id"] for item in page["documents"]] == ["chunk-1", "chunk-2"]
    assert page["has_more"] is True
    assert page["next_cursor"]
    first_sql = _query_text(first_connection.calls[0][0])
    assert "ORDER BY chunk_id ASC" in first_sql
    assert first_connection.calls[0][1][-1] == 3

    second_connection = Connection([])
    monkeypatch.setattr(postgres.psycopg, "connect", lambda *args, **kwargs: second_connection)
    second_vector = PostgresVectorClient(dense=Dense(), database_url="postgresql://db/rag")
    with second_vector.app_scope("acme"):
        second_vector.list_chunks(limit=2, cursor=page["next_cursor"])

    second_sql = _query_text(second_connection.calls[0][0])
    assert "chunk_id > %s" in second_sql
    assert second_connection.calls[0][1] == ("chunk-2", 3)


def test_chunk_listing_rejects_invalid_limit_and_cursor(monkeypatch):
    vector = _client(monkeypatch, Connection([]))

    with vector.app_scope("acme"):
        with pytest.raises(ValueError, match="limit"):
            vector.list_chunks(limit=0)
        with pytest.raises(ValueError, match="invalid cursor"):
            vector.list_chunks(cursor="not-a-cursor")


def test_query_uses_configured_connection_and_statement_timeouts(monkeypatch):
    connection = Connection([])
    connect_calls = []

    def connect(database_url, **kwargs):
        connect_calls.append((database_url, kwargs))
        return connection

    monkeypatch.setattr(postgres.psycopg, "connect", connect)
    vector = PostgresVectorClient(
        dense=Dense(),
        database_url="postgresql://db/rag",
        timeout=7,
        query_timeout=11,
    )

    with vector.app_scope("acme"):
        vector.list_chunks()

    assert connect_calls == [(
        "postgresql://db/rag",
        {
            "autocommit": True,
            "row_factory": postgres.dict_row,
            "connect_timeout": 7,
            "options": "-c statement_timeout=11000",
        },
    )]


def test_query_retries_after_discarding_a_broken_connection(monkeypatch):
    class BrokenConnection(Connection):
        def execute(self, query, params=None):
            raise psycopg.OperationalError("connection lost")

    broken = BrokenConnection()
    healthy = Connection([])
    connections = iter([broken, healthy])
    monkeypatch.setattr(postgres.psycopg, "connect", lambda *args, **kwargs: next(connections))
    vector = PostgresVectorClient(
        dense=Dense(),
        database_url="postgresql://db/rag",
        retry=RetryConfig(max_attempts=2, interval_seconds=0),
    )

    with vector.app_scope("acme"):
        assert vector.list_chunks()["documents"] == []

    assert broken.closed is True
