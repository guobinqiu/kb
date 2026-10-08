import pytest
import psycopg
from psycopg import sql

from kb_api.rag_indexer.common.config import RetryConfig
from kb_api.rag_indexer.core.scope import app_collection


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True
    vector_size = 3

    def __init__(self):
        self.documents = []

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class RecordingCursor:
    def __init__(self, responses=None, rowcounts=None):
        self.responses = list(responses or [])
        self.rowcounts = list(rowcounts or [])
        self.calls = []
        self._response = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))
        self._response = self.responses.pop(0) if self.responses else None
        self.rowcount = self.rowcounts.pop(0) if self.rowcounts else -1
        return self

    def executemany(self, query, params_seq):
        self.calls.append((query, list(params_seq)))
        self._response = self.responses.pop(0) if self.responses else None
        self.rowcount = self.rowcounts.pop(0) if self.rowcounts else -1
        return self

    def fetchone(self):
        if isinstance(self._response, list):
            return self._response[0] if self._response else None
        return self._response

    def fetchall(self):
        if self._response is None:
            return []
        if isinstance(self._response, list):
            return self._response
        return [self._response]


class RecordingConnection:
    def __init__(self, responses=None, rowcounts=None):
        self.recording_cursor = RecordingCursor(responses, rowcounts)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.recording_cursor


def _client(monkeypatch, *, responses=None, rowcounts=None, bm25=True, dense=None):
    from kb_api.rag_indexer.clients.vector import postgres

    connection = RecordingConnection(responses, rowcounts)
    monkeypatch.setattr(postgres.psycopg, "connect", lambda *args, **kwargs: connection)
    client = postgres.PostgresVectorClient(
        dense=dense or FakeDense(),
        database_url="postgresql://test",
        bm25=bm25,
    )
    client.start()
    return client, connection.recording_cursor


def _sql_calls(cursor):
    return [query.as_string(None) if isinstance(query, sql.Composable) else str(query) for query, _ in cursor.calls]


def _chunk(chunk_id="chunk-1", content="knowledge", chunk_index=0):
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {
            "file_id": "ignored",
            "workspace_id": "workspace-a",
            "filename": "faq.pdf",
            "chunk_index": chunk_index,
            "s3_url": "s3://bucket/faq.pdf",
        },
    }


def test_postgres_provider_capabilities_follow_bm25_switch(monkeypatch):
    enabled, _ = _client(monkeypatch, bm25=True)
    disabled, _ = _client(monkeypatch, bm25=False)

    assert enabled.backend_name == "postgres"
    assert enabled.ready is True
    assert enabled.supports_dense_vector() is True
    assert enabled.supports_sparse_vector() is True
    assert disabled.supports_sparse_vector() is False


def test_ensure_app_collection_uses_identifiers_and_required_schema(monkeypatch):
    client, cursor = _client(monkeypatch, responses=[(None,)], bm25=True)

    assert client.ensure_app_collection("imsdom") == "imsdom_chunks"

    statements = _sql_calls(cursor)
    create_table = next(statement for statement in statements if statement.startswith("CREATE TABLE"))
    assert 'CREATE TABLE IF NOT EXISTS "imsdom_chunks"' in create_table
    assert "key_id BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE" in create_table
    assert "chunk_id TEXT PRIMARY KEY" in create_table
    assert "embedding vector(3) NOT NULL" in create_table
    assert any('ON "imsdom_chunks" (file_id, chunk_index)' in statement for statement in statements)
    assert any(
        'USING bm25 (key_id, content) WITH (key_field=\'key_id\')' in statement
        for statement in statements
    )


def test_ensure_app_collection_omits_bm25_index_when_disabled(monkeypatch):
    client, cursor = _client(monkeypatch, responses=[(None,)], bm25=False)

    client.ensure_app_collection("imsdom")

    assert all("USING bm25" not in statement for statement in _sql_calls(cursor))


def test_ensure_app_collection_rejects_dense_dimension_mismatch(monkeypatch):
    client, _ = _client(monkeypatch, responses=[("vector(768)",)])

    with pytest.raises(ValueError, match="dense vector dimension mismatch: expected 3, actual 768"):
        client.ensure_app_collection("imsdom")


def test_uppercase_collection_dimension_check_uses_exact_table_name(monkeypatch):
    client, cursor = _client(monkeypatch, responses=[("vector(3)",)])

    client.ensure_app_collection("Acme")

    statement = _sql_calls(cursor)[0]
    assert "JOIN pg_class" in statement
    assert "JOIN pg_namespace" in statement
    assert "to_regclass" not in statement
    assert cursor.calls[0][1] == ("Acme_chunks",)


def test_add_file_chunks_upserts_rows_then_deletes_stale_tail(monkeypatch):
    dense = FakeDense()
    client, cursor = _client(monkeypatch, rowcounts=[2, 1], dense=dense)
    chunks = [_chunk("chunk-0", "first", 0), _chunk("chunk-1", "second", 1)]

    with app_collection("imsdom"):
        assert client.add_file_chunks(chunks, "file-a") == 2

    statements = _sql_calls(cursor)
    assert dense.documents == [["first", "second"]]
    assert 'INSERT INTO "imsdom_chunks"' in statements[0]
    assert "ON CONFLICT (chunk_id) DO UPDATE" in statements[0]
    first_row = cursor.calls[0][1][0]
    assert first_row[:7] == (
        "chunk-0",
        "first",
        "file-a",
        "workspace-a",
        0,
        "faq.pdf",
        "s3://bucket/faq.pdf",
    )
    assert first_row[7].obj == {"file_id": "file-a", "workspace_id": "workspace-a", "filename": "faq.pdf", "chunk_index": 0, "s3_url": "s3://bucket/faq.pdf"}
    assert first_row[8] == "[0.1,0.2,0.3]"
    assert 'DELETE FROM "imsdom_chunks" WHERE file_id = %s AND chunk_index >= %s' in statements[1]
    assert cursor.calls[1][1] == ("file-a", 2)


def test_delete_count_and_stale_operations_use_bound_values(monkeypatch):
    client, cursor = _client(
        monkeypatch,
        responses=[("imsdom_chunks",), None, ("imsdom_chunks",), None, (7,)],
        rowcounts=[-1, 4, -1, 2, -1],
    )

    with app_collection("imsdom"):
        assert client.delete_file_chunks("file-a") == 4
        assert client.delete_stale_file_chunks("file-a", 3) == 2
        assert client.get_total_chunks(["file-a", "file-b"]) == 7

    statements = _sql_calls(cursor)
    assert statements[1] == 'DELETE FROM "imsdom_chunks" WHERE file_id = %s'
    assert cursor.calls[1][1] == ("file-a",)
    assert "file_id = ANY(%s)" in statements[4]
    assert cursor.calls[4][1] == (["file-a", "file-b"],)


def test_delete_file_chunks_is_noop_when_collection_does_not_exist(monkeypatch):
    client, cursor = _client(monkeypatch, responses=[None])

    with app_collection("imsdom"):
        assert client.delete_file_chunks("file-a") == 0

    assert all(not statement.startswith("DELETE FROM") for statement in _sql_calls(cursor))


def test_list_chunks_paginates_and_get_dense_vector(monkeypatch):
    rows = [
        ("chunk-a", "first", {"file_id": "file-a", "filename": "a.pdf", "chunk_index": 0}),
        ("chunk-b", "second", {"file_id": "file-a", "filename": "a.pdf", "chunk_index": 1}),
        ("chunk-c", "third", {"file_id": "file-a", "filename": "a.pdf", "chunk_index": 2}),
    ]
    client, cursor = _client(monkeypatch, responses=[rows, ([0.1, 0.2, 0.3],)])

    with app_collection("imsdom"):
        first_page = client.list_chunks(file_ids=["file-a"], limit=2)
        vector = client.get_dense_vector("chunk-a")

    assert [item["id"] for item in first_page["documents"]] == ["chunk-a", "chunk-b"]
    assert first_page["has_more"] is True
    assert first_page["next_cursor"] is not None
    assert vector == [0.1, 0.2, 0.3]
    assert "file_id = ANY(%s)" in _sql_calls(cursor)[0]
    assert cursor.calls[0][1] == (["file-a"], 3)
    assert cursor.calls[1][1] == ("chunk-a",)


def test_app_lifecycle_and_scope_use_current_collection(monkeypatch):
    client, cursor = _client(
        monkeypatch,
        responses=[("imsdom_chunks",), ("imsdom_chunks",), None, (1,)],
    )

    assert client.app_collection_exists("imsdom") is True
    assert client.drop_app_collection("imsdom") is True
    with client.app_scope("imsdom"):
        assert client.get_total_chunks() == 1

    statements = _sql_calls(cursor)
    assert cursor.calls[0][1] == ("imsdom_chunks",)
    assert statements[2] == 'DROP TABLE IF EXISTS "imsdom_chunks"'
    assert statements[3] == 'SELECT COUNT(*) FROM "imsdom_chunks"'


def test_uppercase_collection_exists_uses_exact_table_name(monkeypatch):
    client, cursor = _client(monkeypatch, responses=[("Acme_chunks",)])

    assert client.app_collection_exists("Acme") is True

    statement = _sql_calls(cursor)[0]
    assert "information_schema.tables" in statement
    assert "to_regclass" not in statement
    assert cursor.calls[0][1] == ("Acme_chunks",)


def test_invalid_app_id_is_rejected_before_sql(monkeypatch):
    client, cursor = _client(monkeypatch)

    with pytest.raises(ValueError, match="app_id"):
        client.ensure_app_collection('bad"; DROP TABLE users; --')

    assert cursor.calls == []


def test_query_uses_configured_connection_and_statement_timeouts(monkeypatch):
    from kb_api.rag_indexer.clients.vector import postgres

    connection = RecordingConnection(responses=[(1,)])
    connect_calls = []

    def connect(database_url, **kwargs):
        connect_calls.append((database_url, kwargs))
        return connection

    monkeypatch.setattr(postgres.psycopg, "connect", connect)
    client = postgres.PostgresVectorClient(
        dense=FakeDense(),
        database_url="postgresql://test",
        timeout=7,
        query_timeout=11,
    )
    client.start()

    with app_collection("imsdom"):
        assert client.get_total_chunks() == 1

    assert connect_calls == [(
        "postgresql://test",
        {"connect_timeout": 7, "options": "-c statement_timeout=11000"},
    )]


def test_query_retries_with_a_new_connection_after_operational_error(monkeypatch):
    from kb_api.rag_indexer.clients.vector import postgres

    class BrokenCursor(RecordingCursor):
        def execute(self, query, params=None):
            raise psycopg.OperationalError("connection lost")

    class BrokenConnection(RecordingConnection):
        def __init__(self):
            self.recording_cursor = BrokenCursor()

    connections = iter([BrokenConnection(), RecordingConnection(responses=[(2,)])])
    monkeypatch.setattr(postgres.psycopg, "connect", lambda *args, **kwargs: next(connections))
    client = postgres.PostgresVectorClient(
        dense=FakeDense(),
        database_url="postgresql://test",
        retry=RetryConfig(max_attempts=2, interval_seconds=0),
    )
    client.start()

    with app_collection("imsdom"):
        assert client.get_total_chunks() == 2
