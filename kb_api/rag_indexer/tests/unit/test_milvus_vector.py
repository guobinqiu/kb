from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from kb_api.rag_indexer.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_indexer.clients.vector import milvus
from kb_api.rag_indexer.core.scope import app_collection
from kb_api.rag_indexer.clients.vector.milvus import _metadata_payload_filter


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True

    def __init__(self):
        self.queries = []
        self.documents = []

    def start(self):
        pass

    def embed_query(self, query):
        self.queries.append(query)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeMilvusClient:
    instances = []

    def __init__(self, uri, timeout=None, token=None, grpc_options=None, dedicated=False):
        self.uri = uri
        self.timeout = timeout
        self.token = token
        self.collections = set()
        self.created = []
        self.indexed = []
        self.loaded = []
        self.inserted = []
        self.upserted = []
        self.deleted = []
        self.flushed = []
        self.searches = []
        self.hybrid_searches = []
        self.queries = []
        self.gets = []
        self.dropped = []
        self.closed = False
        FakeMilvusClient.instances.append(self)

    @classmethod
    def create_schema(cls, **kwargs):
        return FakeSchema(**kwargs)

    @classmethod
    def prepare_index_params(cls, field_name="", **kwargs):
        return FakeIndexParams(field_name, kwargs)

    def has_collection(self, collection_name, **kwargs):
        return collection_name in self.collections

    def create_collection(self, **kwargs):
        self.collections.add(kwargs["collection_name"])
        self.created.append(kwargs)

    def create_index(self, **kwargs):
        self.indexed.append(kwargs)

    def describe_collection(self, collection_name, timeout=None, **kwargs):
        if hasattr(self, "collection_schema"):
            return self.collection_schema
        return {
            "fields": [{"name": "pk"}, {"name": "text"}, {"name": "vector"}, {"name": "sparse_vector"}],
            "functions": [{"name": "text_bm25", "type": milvus.pymilvus.FunctionType.BM25}],
        }

    def load_collection(self, collection_name, timeout=None, **kwargs):
        self.loaded.append((collection_name, timeout))

    def insert(self, collection_name, data, timeout=None):
        self.inserted.append((collection_name, data, timeout))

    def upsert(self, collection_name, data, timeout=None, **kwargs):
        self.upserted.append((collection_name, data, timeout))

    def search(self, collection_name, **kwargs):
        self.searches.append((collection_name, kwargs))
        return [[{"id": "pk1", "distance": 0.25, "entity": {"pk": "pk1", "text": "hello", "file_id": "file1"}}]]

    def hybrid_search(self, collection_name, **kwargs):
        self.hybrid_searches.append((collection_name, kwargs))
        return [[{"id": "pk1", "distance": 1.0, "entity": {"pk": "pk1", "text": "hello", "file_id": "file1"}}]]

    def query(self, collection_name, **kwargs):
        self.queries.append((collection_name, kwargs))
        if kwargs.get("output_fields") == ["count(*)"]:
            return [{"count(*)": 2}]
        if kwargs.get("output_fields") == ["pk"]:
            return [{"pk": "pk1"}]
        if hasattr(self, "query_rows"):
            rows = self.query_rows[min(len(self.queries) - 1, len(self.query_rows) - 1)]
            return rows
        return [{"pk": "pk1", "text": "hello", "file_id": "file1", "filename": "a.txt", "chunk_index": 0}]

    def get(self, collection_name, ids, output_fields=None, timeout=None):
        self.gets.append((collection_name, ids, output_fields, timeout))
        return [{"pk": ids[0], "vector": [0.1, 0.2, 0.3]}]

    def delete(self, collection_name, ids, timeout=None, **kwargs):
        self.deleted.append((collection_name, ids, timeout))

    def flush(self, collection_name, timeout=None, **kwargs):
        self.flushed.append((collection_name, timeout))

    def drop_collection(self, collection_name, **kwargs):
        self.dropped.append((collection_name, kwargs))
        self.collections.discard(collection_name)

    def close(self):
        self.closed = True


class FakeSchema:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fields = []
        self.functions = []

    def add_field(self, **kwargs):
        self.fields.append(kwargs)

    def add_function(self, function):
        self.functions.append(function)


class FakeIndexParams:
    def __init__(self, field_name, kwargs):
        self.field_name = field_name
        self.kwargs = kwargs
        self.indexes = []

    def add_index(self, **kwargs):
        self.indexes.append(kwargs)


def _started_vector(
    client=None,
    dense=None,
    uri="http://localhost:19530",
    timeout=None,
    query_timeout=None,
    write_timeout=None,
    init_timeout=None,
    drop_timeout=None,
):

    vector = MilvusVectorClient(
        dense=dense or FakeDense(),
        uri=uri,
        timeout=timeout,
        query_timeout=query_timeout,
        write_timeout=write_timeout,
        init_timeout=init_timeout,
        drop_timeout=drop_timeout,
    )
    vector.client = client
    vector.start()
    return vector


def test_milvus_vector_resolves_local_lite_uri_from_project_root(tmp_path):

    project_root = tmp_path / "rag"
    backend_dir = project_root / "backend"
    backend_dir.mkdir(parents=True)

    uri = milvus._connection_uri("milvus_data/lite/lite.db", project_root=project_root)

    assert uri == str(project_root / "milvus_data" / "lite" / "lite.db")
    assert (project_root / "milvus_data" / "lite").is_dir()


@pytest.mark.parametrize("uri", ["http://localhost:19530", "https://cluster.example.invalid", "https://cluster.example.invalid:443"])
def test_milvus_vector_keeps_remote_uri_unchanged(uri):

    assert milvus._connection_uri(uri) == uri


@pytest.mark.parametrize("token", [None, "test-token", "test-user:test-password"])
def test_milvus_vector_passes_cloud_authentication(monkeypatch, token):

    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)
    uri = "https://cluster.example.invalid:443"

    vector = MilvusVectorClient(FakeDense(), uri=uri, timeout=30, token=token)

    assert FakeMilvusClient.instances == []
    client = vector._client()
    assert vector._client() is client
    assert len(FakeMilvusClient.instances) == 1
    assert client.uri == uri
    assert client.timeout == 30
    assert client.token == token


def test_milvus_vector_initializes_one_native_client(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    vector = _started_vector()
    vector.ensure_app_collection("imsdom")

    assert len(FakeMilvusClient.instances) == 1
    assert FakeMilvusClient.instances[0].created[0]["collection_name"] == "imsdom_chunks"


def test_milvus_vector_passes_timeout_to_native_client(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    vector = _started_vector(timeout=30)
    vector.ensure_app_collection("imsdom")

    assert FakeMilvusClient.instances[0].timeout == 30


def test_milvus_drop_collections_uses_configured_timeout_and_disables_controllable_retries():

    client = FakeMilvusClient("http://localhost:19530", timeout=120)
    client.collections.add("imsdom_chunks")
    vector = _started_vector(client=client, timeout=120)

    vector.drop_app_collection("imsdom")
    client.collections.add("imsdom_chunks")
    with app_collection("imsdom"):
        vector.drop_collections()

    assert len(client.dropped) == 2
    for collection_name, options in client.dropped:
        assert collection_name == "imsdom_chunks"
        assert options["timeout"] == 120
        assert options["retry_times"] == 0
        assert options["retry_on_rate_limit"] is False


def test_milvus_vector_start_does_not_probe_dense_model(monkeypatch):
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)
    dense = FakeDense()

    vector = _started_vector(dense=dense)

    assert vector.ready is True
    assert dense.queries == []


def test_milvus_ensure_app_collection_propagates_first_failure(monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    class FlakyMilvusClient(FakeMilvusClient):
        def has_collection(self, collection_name, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("milvus not ready")
            return super().has_collection(collection_name)

    monkeypatch.setattr("pymilvus.MilvusClient", FlakyMilvusClient)
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    vector = _started_vector()
    with pytest.raises(RuntimeError, match="milvus not ready"):
        vector.ensure_app_collection("imsdom")

    assert attempts["count"] == 1
    assert sleeps == []
    assert vector.ready is True


def test_milvus_stop_closes_native_client():
    client = FakeMilvusClient("http://localhost:19530")
    vector = _started_vector(client=client)

    vector.stop()

    assert client.closed is True
    assert vector.client is None


def test_milvus_search_and_query_use_configured_timeout():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        vector.search_dense("query", 5, "file_id in ['file_a']")
        vector.list_chunks(file_ids=["file_a"])

    assert client.searches[0][1]["timeout"] == 30
    assert client.queries[0][1]["timeout"] == 30


def test_milvus_vector_uses_split_operation_timeouts():

    client = FakeMilvusClient("http://localhost:19530", timeout=10)
    vector = _started_vector(
        client=client,
        timeout=30,
        query_timeout=10,
        write_timeout=60,
        init_timeout=120,
        drop_timeout=180,
    )

    vector.ensure_app_collection("imsdom")
    with app_collection("imsdom"):
        vector.add_file_chunks([{"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}}], "file-a")
        vector.search_dense("query", 5, "")
        vector.drop_collections()

    assert client.created[0]["timeout"] == 120
    assert client.indexed[0]["timeout"] == 120
    assert client.loaded[0][1] == 120
    assert client.upserted[0][2] == 60
    assert client.flushed == []
    assert client.searches[0][1]["timeout"] == 10
    assert client.dropped[0][1]["timeout"] == 180


def test_milvus_get_total_chunks_uses_count_query_with_non_empty_filter():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        total = vector.get_total_chunks()

    assert total == 2
    assert client.queries[0][0] == "imsdom_chunks"
    assert client.queries[0][1]["filter"] == 'pk != ""'
    assert client.queries[0][1]["output_fields"] == ["count(*)"]
    assert "limit" not in client.queries[0][1]


def test_milvus_get_total_chunks_with_file_ids_uses_file_filter():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        total = vector.get_total_chunks(["file-a"])

    assert total == 2
    assert client.queries[0][1]["filter"] == "file_id in ['file-a']"
    assert client.queries[0][1]["output_fields"] == ["count(*)"]


def test_metadata_filter_combines_file_and_workspace_ids():

    assert _metadata_payload_filter(file_ids=["file-a"], workspace_ids=["workspace-a", "workspace-b"]) == (
        "file_id in ['file-a'] and workspace_id in ['workspace-a', 'workspace-b']"
    )


def test_milvus_list_chunks_uses_keyset_cursor():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    client.query_rows = [
        [
            {"pk": "pk1", "text": "hello", "file_id": "file-a", "filename": "a.txt", "chunk_index": 0},
            {"pk": "pk2", "text": "world", "file_id": "file-a", "filename": "a.txt", "chunk_index": 1},
        ],
        [{"pk": "pk2", "text": "world", "file_id": "file-a", "filename": "a.txt", "chunk_index": 1}],
    ]
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        first_page = vector.list_chunks(file_ids=["file-a"], limit=1)
        page = vector.list_chunks(file_ids=["file-a"], limit=2, cursor=first_page["next_cursor"])

    assert [document["id"] for document in page["documents"]] == ["pk2"]
    assert page["next_cursor"] is None
    assert page["has_more"] is False
    assert client.queries[0][0] == "imsdom_chunks"
    assert client.queries[0][1]["filter"] == "file_id in ['file-a']"
    assert client.queries[0][1]["limit"] == 2
    assert client.queries[0][1]["order_by"] == ["pk:asc"]
    assert "offset" not in client.queries[0][1]
    assert 'pk > "pk1"' in client.queries[1][1]["filter"]
    assert client.queries[1][1]["limit"] == 3
    assert client.queries[1][1]["order_by"] == client.queries[0][1]["order_by"]
    assert "offset" not in client.queries[1][1]
    assert client.queries[0][1]["timeout"] == 30


def test_milvus_vector_uses_cosine_metric_for_dense_vectors():
    vector = _started_vector()

    assert vector._search_params_for_mode("dense") == {"metric_type": "COSINE", "params": {}}
    assert vector._search_params_for_mode("hybrid") == {"metric_type": "COSINE", "params": {}}
    assert vector._index_params_for_mode("dense") == {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}}


def test_milvus_get_dense_vector_uses_primary_key_get():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        result = vector.get_dense_vector('chunk-"a"')

    assert result == [0.1, 0.2, 0.3]
    assert client.gets == [("imsdom_chunks", ['chunk-"a"'], ["vector"], 30)]
    assert client.queries == []


def test_milvus_add_file_chunks_serializes_same_file_writes():

    events = []

    class SlowDeleteClient(FakeMilvusClient):
        def query(self, collection_name, **kwargs):
            if kwargs.get("output_fields") == ["pk"]:
                events.append("delete")
                time.sleep(0.05)
                return []
            return super().query(collection_name, **kwargs)

        def upsert(self, collection_name, data, timeout=None, **kwargs):
            events.append("upsert")
            return super().upsert(collection_name, data, timeout)

    client = SlowDeleteClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)
    chunks = [{"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}}]

    def add_chunks():
        with app_collection("imsdom"):
            return vector.add_file_chunks(chunks, "file-a")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(add_chunks) for _ in range(2)]
        [future.result() for future in futures]

    assert events == ["upsert", "delete", "upsert", "delete"]


def test_milvus_add_file_chunks_upserts_before_cleaning_stale_tail():

    events = []

    class OrderedDense(FakeDense):
        def embed_documents(self, texts):
            events.append("embed")
            return super().embed_documents(texts)

    class OrderedClient(FakeMilvusClient):
        def query(self, collection_name, **kwargs):
            if kwargs.get("output_fields") == ["pk"]:
                events.append("delete_query")
            return super().query(collection_name, **kwargs)

        def upsert(self, collection_name, data, timeout=None, **kwargs):
            events.append("upsert")
            return super().upsert(collection_name, data, timeout)

    client = OrderedClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, dense=OrderedDense(), timeout=30)

    with app_collection("imsdom"):
        vector.add_file_chunks([{"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}}], "file-a")

    assert events == ["embed", "upsert", "delete_query"]


def test_milvus_delete_stale_file_chunks_filters_by_file_and_tail_chunk_index():

    client = FakeMilvusClient("http://localhost:19530", timeout=30)
    vector = _started_vector(client=client, timeout=30)

    with app_collection("imsdom"):
        assert vector.delete_stale_file_chunks("file-a", 2) == 1

    assert client.queries[0][1]["filter"] == 'file_id == "file-a" and chunk_index >= 2'
    assert client.queries[0][1]["output_fields"] == ["pk"]


def test_milvus_ensure_collection_rejects_existing_dense_dimension_mismatch():
    class MismatchedCollectionClient(FakeMilvusClient):
        def describe_collection(self, collection_name, timeout=None, **kwargs):
            return {"fields": [{"name": "vector", "params": {"dim": 768}}]}

    client = MismatchedCollectionClient("http://localhost:19530")
    client.collections.add("imsdom_chunks")
    vector = _started_vector(client=client)
    vector.dense_vector_size = 1024

    with pytest.raises(ValueError, match="dense vector dimension mismatch"):
        vector.ensure_collections("imsdom_chunks")


def test_milvus_standalone_uses_explicit_native_index_params():
    vector = _started_vector(uri="http://localhost:19530")

    assert vector._index_params_for_mode("dense") == {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}}


def test_milvus_bm25_index_uses_sparse_inverted_index():
    vector = _started_vector()

    assert dict(vector._index_specs())["sparse_vector"] == {"metric_type": "BM25", "index_type": "SPARSE_INVERTED_INDEX", "params": {}}


def test_milvus_ensure_app_collection_creates_collection_without_placeholder_documents(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    vector = _started_vector(uri="http://localhost:19530")
    vector.ensure_app_collection("imsdom")

    client = FakeMilvusClient.instances[0]
    assert client.collections == {"imsdom_chunks"}
    assert client.created[0]["collection_name"] == "imsdom_chunks"
    indexed_fields = {index["field_name"] for index in client.indexed[0]["index_params"].indexes}
    assert {"file_id", "chunk_index", "workspace_id"} <= indexed_fields
    assert client.inserted == []


def test_milvus_add_file_chunks_upserts_native_rows():

    client = FakeMilvusClient("http://localhost:19530")
    vector = _started_vector(client=client)

    with app_collection("imsdom"):
        count = vector.add_file_chunks([
            {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0, "workspace_id": "workspace-a"}},
        ], "file1")

    assert count == 1
    assert client.upserted[0][0] == "imsdom_chunks"
    assert client.upserted[0][1][0]["pk"] == milvus._point_id("chunk-a")
    assert client.upserted[0][1][0]["text"] == "hello"
    assert client.upserted[0][1][0]["file_id"] == "file1"
    assert client.upserted[0][1][0]["workspace_id"] == "workspace-a"
    assert client.upserted[0][1][0]["vector"] == [0.1, 0.2, 0.3]
    assert client.flushed == []


def test_milvus_add_file_chunks_leaves_sparse_generation_to_bm25_function():

    client = FakeMilvusClient("http://localhost:19530")
    vector = _started_vector(client=client)

    with app_collection("imsdom"):
        vector.add_file_chunks([
            {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}},
        ], "file1")

    assert "sparse_vector" not in client.upserted[0][1][0]


def test_milvus_add_file_chunks_rejects_collection_missing_sparse_field():

    client = FakeMilvusClient("http://localhost:19530")
    client.collections.add("imsdom_chunks")
    client.collection_schema = {"fields": [{"name": "pk"}, {"name": "text"}, {"name": "vector"}]}
    vector = _started_vector(client=client)

    with app_collection("imsdom"), pytest.raises(ValueError, match="missing BM25 sparse_vector field"):
        vector.add_file_chunks([
            {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}},
        ], "file1")

    assert vector.dense.documents == []
    assert client.upserted == []


def test_milvus_add_file_chunks_rejects_external_sparse_collection_without_bm25_function():
    client = FakeMilvusClient("http://localhost:19530")
    client.collections.add("imsdom_chunks")
    client.collection_schema = {
        "fields": [{"name": "pk"}, {"name": "text"}, {"name": "vector"}, {"name": "sparse_vector"}],
        "functions": [],
    }
    vector = _started_vector(client=client)

    with app_collection("imsdom"), pytest.raises(ValueError, match="missing text_bm25 function"):
        vector.add_file_chunks([
            {"id": "chunk-a", "content": "hello", "metadata": {"filename": "a.txt", "chunk_index": 0}},
        ], "file1")

    assert vector.dense.documents == []
    assert client.upserted == []


def test_milvus_create_collection_adds_bm25_function(monkeypatch):
    FakeMilvusClient.instances = []
    monkeypatch.setattr("pymilvus.MilvusClient", FakeMilvusClient)

    vector = _started_vector()
    vector.ensure_app_collection("imsdom")

    schema = FakeMilvusClient.instances[0].created[0]["schema"]
    fields = {field["field_name"]: field for field in schema.fields}
    assert fields["text"]["enable_analyzer"] is True
    assert fields["text"]["analyzer_params"] == {"tokenizer": "jieba"}
    assert "sparse_vector" in fields
    assert [function.to_dict() for function in schema.functions] == [{
        "name": "text_bm25",
        "description": "",
        "type": milvus.pymilvus.FunctionType.BM25,
        "input_field_names": ["text"],
        "output_field_names": ["sparse_vector"],
        "params": {},
    }]


def test_milvus_sparse_search_sends_raw_query_to_bm25_function():

    client = FakeMilvusClient("http://localhost:19530")
    vector = _started_vector(client=client)

    with app_collection("imsdom"):
        vector.search_sparse("query", 3, "")

    assert client.searches[0][1]["anns_field"] == "sparse_vector"
    assert client.searches[0][1]["data"] == ["query"]
