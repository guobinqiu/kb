import pytest


pytestmark = pytest.mark.unit


class FakeDense:
    ready = True

    def __init__(self):
        self.queries = []
        self.documents = []

    def embed_query(self, text):
        self.queries.append(text)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeSparse:
    ready = True

    def __init__(self):
        self.queries = []
        self.documents = []

    def embed_query(self, text):
        self.queries.append(text)
        return {1: 0.5, 8: 1.0}

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [{1: 0.5, 8: 1.0} for _ in texts]


class FakeCount:
    count = 0


def _chunk(chunk_id="chunk-1", content="通用知识"):
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": "faq.pdf", "chunk_index": 0},
    }


def _started_vector(client, dense=None, sparse=None, **kwargs):
    from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient

    vector = QdrantVectorClient(dense=dense or FakeDense(), sparse=sparse, **kwargs)
    vector.client = client
    vector.start()
    return vector


def test_add_file_chunks_writes_file_metadata():
    from kb_api.rag_indexer.core.scope import app_collection
    from kb_api.rag_indexer.clients.vector import qdrant

    calls = []

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs["collection_name"], kwargs["points"]))

    vector = _started_vector(FakeClient())

    with app_collection("imsdom"):
        assert vector.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="550e8400-e29b-41d4-a716-446655440000") == 1

    _, collection_name, points = calls[0]
    assert collection_name == "imsdom_chunks"
    assert points[0].id == qdrant._point_id("chunk-1")
    assert points[0].payload["content"] == "华为给我们一万六千张卡"
    assert points[0].payload["metadata"]["file_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert points[0].payload["metadata"]["chunk_index"] == 0
    assert points[0].payload["metadata"]["filename"] == "faq.pdf"


def test_add_file_chunks_writes_sparse_vector_when_configured():
    from kb_api.rag_indexer.core.scope import app_collection

    calls = []

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            calls.append(kwargs["points"])

    vector = _started_vector(FakeClient(), sparse=FakeSparse())

    with app_collection("imsdom"):
        vector.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="file-a")

    sparse = calls[0][0].vector["sparse"]
    assert sparse.indices == [1, 8]
    assert sparse.values == [0.5, 1.0]


def test_metadata_filter_combines_file_and_workspace_ids():
    from kb_api.rag_indexer.clients.vector.qdrant import _metadata_payload_filter

    metadata_filter = _metadata_payload_filter(file_ids=["file-a"], workspace_ids=["workspace-a", "workspace-b"])

    assert [(item.key, item.match.any) for item in metadata_filter.must] == [
        ("metadata.file_id", ["file-a"]),
        ("metadata.workspace_id", ["workspace-a", "workspace-b"]),
    ]


def test_add_file_chunks_upserts_before_cleaning_stale_tail():
    from kb_api.rag_indexer.core.scope import app_collection

    events = []

    class OrderedDense(FakeDense):
        def embed_documents(self, texts):
            events.append("embed")
            return super().embed_documents(texts)

    class FakeClient:
        def count(self, **kwargs):
            events.append("count")
            return FakeCount()

        def upsert(self, **kwargs):
            events.append("upsert")

    vector = _started_vector(FakeClient(), dense=OrderedDense())

    with app_collection("imsdom"):
        vector.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="file_a")

    assert events == ["embed", "upsert", "count"]


def test_delete_stale_file_chunks_filters_by_file_and_tail_chunk_index():
    from kb_api.rag_indexer.clients.vector import qdrant
    from kb_api.rag_indexer.core.scope import app_collection

    filters = []

    class FakeClient:
        def count(self, **kwargs):
            filters.append(kwargs["count_filter"])
            return FakeCount()

    vector = _started_vector(FakeClient())

    with app_collection("imsdom"):
        assert vector.delete_stale_file_chunks("file-a", 2) == 0

    conditions = filters[0].must
    assert conditions[0].key == "metadata.file_id"
    assert conditions[0].match == qdrant.models.MatchValue(value="file-a")
    assert conditions[1].key == "metadata.chunk_index"
    assert conditions[1].range == qdrant.models.Range(gte=2)


def test_add_file_chunks_logs_backend_retriever_and_stage_fields(caplog):
    import logging
    from kb_api.rag_indexer.core.scope import app_collection

    class FakeClient:
        def count(self, **kwargs):
            return FakeCount()

        def upsert(self, **kwargs):
            pass

    vector = _started_vector(FakeClient())

    with caplog.at_level(logging.INFO, logger="kb_api.rag_indexer.core.indexing"):
        with app_collection("imsdom"):
            vector.add_file_chunks([_chunk(content="华为给我们一万六千张卡")], file_id="file_a")

    records = {record.event: record for record in caplog.records if hasattr(record, "event")}
    assert records["dense_embedding_start"].app_id == "imsdom"
    assert records["dense_embedding_start"].stage == "embedding"
    assert records["dense_embedding_start"].backend == "model"
    assert records["dense_embedding_start"].retriever == "dense"
    assert records["dense_embedding_done"].status == "ok"
    assert records["qdrant_upsert_start"].stage == "index"
    assert records["qdrant_upsert_start"].backend == "qdrant"
    assert records["qdrant_upsert_start"].retriever == "vector"
    assert records["qdrant_upsert_done"].status == "ok"


def test_ensure_payload_indexes_creates_file_id_and_chunk_index_indexes():
    from kb_api.rag_indexer.clients.vector import qdrant

    calls = []

    class FakeClient:
        def create_payload_index(self, **kwargs):
            calls.append((kwargs["collection_name"], kwargs["field_name"], kwargs["field_schema"]))

    vector = _started_vector(FakeClient())
    vector.ensure_payload_indexes("imsdom_chunks")

    assert calls == [
        ("imsdom_chunks", "metadata.file_id", qdrant.models.PayloadSchemaType.KEYWORD),
        ("imsdom_chunks", "metadata.chunk_index", qdrant.models.PayloadSchemaType.INTEGER),
        ("imsdom_chunks", "metadata.workspace_id", qdrant.models.PayloadSchemaType.KEYWORD),
    ]


def test_qdrant_vector_uses_split_operation_timeouts():
    from kb_api.rag_indexer.core.scope import app_collection

    calls = []

    class FakeClient:
        exists = False

        def collection_exists(self, collection_name, **kwargs):
            calls.append(("exists", kwargs.get("timeout")))
            return self.exists

        def create_collection(self, **kwargs):
            calls.append(("create", kwargs.get("timeout")))
            self.exists = True

        def get_collection(self, collection_name, **kwargs):
            calls.append(("get", kwargs.get("timeout")))
            return object()

        def count(self, **kwargs):
            calls.append(("count", kwargs.get("timeout")))
            return FakeCount()

        def create_payload_index(self, **kwargs):
            calls.append(("payload_index", kwargs.get("timeout")))

        def upsert(self, **kwargs):
            calls.append(("upsert", kwargs.get("timeout")))

        def query_points(self, **kwargs):
            calls.append(("query", kwargs.get("timeout")))
            return type("Response", (), {"points": []})()

        def delete_collection(self, collection_name, **kwargs):
            calls.append(("drop", kwargs.get("timeout")))

    vector = _started_vector(
        FakeClient(),
        query_timeout=10,
        write_timeout=60,
        init_timeout=120,
        drop_timeout=180,
    )

    vector.ensure_app_collection("imsdom")
    with app_collection("imsdom"):
        vector.add_file_chunks([_chunk(content="hello")], file_id="file-a")
        vector.search_dense("query", 5, None)
        vector.drop_collections()

    assert ("create", 120) in calls
    assert ("exists", None) in calls
    assert ("get", None) in calls
    assert ("payload_index", 120) in calls
    assert ("upsert", 60) in calls
    assert ("query", 10) in calls
    assert ("drop", 180) in calls


def test_ensure_payload_indexes_raises_when_index_creation_fails():
    vector = _started_vector(FailingPayloadIndexClient())

    with pytest.raises(RuntimeError, match="payload index failed"):
        vector.ensure_payload_indexes("imsdom_chunks")


class FailingPayloadIndexClient:
    def create_payload_index(self, **kwargs):
        raise RuntimeError("payload index failed")


def test_add_file_chunks_requires_file_id():
    vector = _started_vector(client=None)

    with pytest.raises(ValueError, match="file_id"):
        vector.add_file_chunks([_chunk(content="x")], file_id="")


def test_point_id_keeps_standard_uuid_chunk_id():
    import uuid
    from kb_api.rag_indexer.clients.vector import qdrant

    chunk_id = str(uuid.uuid4())
    point_id = qdrant._point_id(chunk_id)

    assert point_id == chunk_id
    assert str(uuid.UUID(point_id)) == point_id


def test_qdrant_client_uses_configured_timeout(monkeypatch):
    from kb_api.rag_indexer.clients.vector import qdrant

    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(qdrant, "QdrantClient", FakeClient)

    vector = qdrant.QdrantVectorClient(dense=FakeDense(), url="http://localhost:6333", timeout=30)
    vector._client()

    assert created[0]["timeout"] == 30


@pytest.mark.parametrize("url", ["https://cluster.example.invalid", "https://cluster.example.invalid:6333", "https://cluster.example.invalid:443"])
@pytest.mark.parametrize("api_key", [None, "test-api-key"])
def test_qdrant_client_passes_cloud_authentication(monkeypatch, url, api_key):
    from kb_api.rag_indexer.clients.vector import qdrant
    from kb_api.rag_indexer.common.config import QdrantQuantizationConfig

    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(qdrant, "QdrantClient", FakeClient)
    quantization = QdrantQuantizationConfig(enable=True)

    vector = qdrant.QdrantVectorClient(FakeDense(), None, url, 30, quantization, api_key=api_key)

    assert created == []
    client = vector._client()
    assert vector._client() is client
    assert vector.quantization is quantization
    assert created == [{"url": url, "timeout": 30, "check_compatibility": False, "api_key": api_key}]


def test_qdrant_list_chunks_uses_native_scroll_cursor_without_full_scan():
    from kb_api.rag_indexer.core.scope import app_collection

    calls = []

    class FakeRecord:
        def __init__(self, point_id, file_id, chunk_index):
            self.id = point_id
            self.payload = {
                "content": f"{file_id} chunk text {chunk_index}",
                "metadata": {"file_id": file_id, "filename": f"{file_id}.txt", "chunk_index": chunk_index},
            }

    class FakeClient:
        def scroll(self, **kwargs):
            calls.append(kwargs)
            if kwargs["offset"] is None:
                return [
                    FakeRecord("a-0", "file-a", 0),
                    FakeRecord("b-0", "file-b", 0),
                    FakeRecord("c-0", "file-c", 0),
                    FakeRecord("a-1", "file-a", 1),
                ], "next"
            return [
                FakeRecord("b-1", "file-b", 1),
                FakeRecord("c-1", "file-c", 1),
                FakeRecord("a-2", "file-a", 2),
                FakeRecord("b-2", "file-b", 2),
            ], None

    vector = _started_vector(FakeClient())

    with app_collection("imsdom"):
        first_page = vector.list_chunks(limit=4)
        page = vector.list_chunks(limit=4, cursor=first_page["next_cursor"])

    assert [document["id"] for document in first_page["documents"]] == ["a-0", "b-0", "c-0", "a-1"]
    assert [document["id"] for document in page["documents"]] == ["b-1", "c-1", "a-2", "b-2"]
    assert page["next_cursor"] is None
    assert page["has_more"] is False
    assert calls[0]["collection_name"] == "imsdom_chunks"
    assert calls[0]["limit"] == 4
    assert "order_by" not in calls[0]
    assert calls[0]["offset"] is None
    assert calls[1]["offset"] == "next"
    assert calls[0]["with_vectors"] is False


def test_qdrant_reads_dense_vector_by_chunk_id():
    from kb_api.rag_indexer.core.scope import app_collection

    calls = []

    class FakeRecord:
        id = "chunk-a"
        vector = {
            "dense": [0.1, 0.2],
        }

    class FakeClient:
        def retrieve(self, **kwargs):
            calls.append(kwargs)
            return [FakeRecord()]

    vector = _started_vector(FakeClient())

    with app_collection("imsdom"):
        dense = vector.get_dense_vector("chunk-a")

    assert dense == [0.1, 0.2]
    assert calls[0] == {
        "collection_name": "imsdom_chunks",
        "ids": ["chunk-a"],
        "with_payload": False,
        "with_vectors": True,
        "timeout": 30,
    }


def test_vector_start_does_not_create_collection():
    dense = FakeDense()
    vector = _started_vector(client=None, dense=dense)

    assert vector.ready is True
    assert dense.queries == []


def test_qdrant_create_collection_can_enable_int8_quantization():
    from kb_api.rag_indexer.common.config import QdrantQuantizationConfig

    calls = []

    class FakeClient:
        def collection_exists(self, collection_name, **kwargs):
            return False

        def create_collection(self, **kwargs):
            calls.append(kwargs)

        def get_collection(self, collection_name, **kwargs):
            return object()

        def count(self, **kwargs):
            return object()

        def create_payload_index(self, **kwargs):
            pass

    vector = _started_vector(FakeClient())
    vector.quantization = QdrantQuantizationConfig(enable=True, type="int8", quantile=0.99, always_ram=True)
    vector.ensure_collections("imsdom_chunks")

    quantization = calls[0]["quantization_config"]
    assert quantization.scalar.type == "int8"
    assert quantization.scalar.quantile == 0.99
    assert quantization.scalar.always_ram is True


def test_qdrant_create_collection_adds_sparse_vector_when_configured():
    calls = []

    class FakeClient:
        def collection_exists(self, collection_name, **kwargs):
            return False

        def create_collection(self, **kwargs):
            calls.append(kwargs)

        def get_collection(self, collection_name, **kwargs):
            return object()

        def count(self, **kwargs):
            return object()

        def create_payload_index(self, **kwargs):
            pass

    vector = _started_vector(FakeClient(), sparse=FakeSparse())
    vector.ensure_collections("imsdom_chunks")

    assert "sparse" in calls[0]["sparse_vectors_config"]


def test_qdrant_sparse_search_uses_sparse_vector_name():
    from kb_api.rag_indexer.core.scope import app_collection

    calls = []

    class FakeResponse:
        points = []

    class FakeClient:
        def query_points(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    vector = _started_vector(FakeClient(), sparse=FakeSparse())

    with app_collection("imsdom"):
        vector.search_sparse("query", 3, None)

    assert calls[0]["using"] == "sparse"
    assert calls[0]["query"].indices == [1, 8]


def test_qdrant_ensure_collection_rejects_existing_dense_dimension_mismatch():
    class VectorParams:
        size = 768

    class Params:
        vectors = {"dense": VectorParams()}

    class Config:
        params = Params()

    class CollectionInfo:
        config = Config()

    class FakeClient:
        def collection_exists(self, collection_name, **kwargs):
            return True

        def get_collection(self, collection_name, **kwargs):
            return CollectionInfo()

        def create_payload_index(self, **kwargs):
            pass

    vector = _started_vector(FakeClient())
    vector.dense_vector_size = 1024

    with pytest.raises(ValueError, match="dense vector dimension mismatch"):
        vector.ensure_collections("imsdom_chunks")


def test_decode_chunk_cursor_returns_native_scroll_offset():
    from kb_api.rag_indexer.clients.vector.qdrant import _decode_chunk_cursor, _encode_chunk_cursor

    cursor = _encode_chunk_cursor("next-offset")

    assert _decode_chunk_cursor(cursor) == "next-offset"
