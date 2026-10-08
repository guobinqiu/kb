import pytest

from kb_api.rag_search.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_search.clients.vector.qdrant import QdrantVectorClient
from kb_api.rag_search.clients.vector import qdrant
from kb_api.rag_search.core.scope import app_collection


class RoutedDense:
    vector_size = 768


def test_milvus_search_filter_scopes_files_and_workspaces():
    vector = MilvusVectorClient(dense=object())

    assert vector.build_metadata_filter(["file-a"], ["workspace-a", "workspace-b"]) == (
        "file_id in ['file-a'] and workspace_id in ['workspace-a', 'workspace-b']"
    )
    assert vector.build_metadata_filter(workspace_ids=["workspace-a"]) == "workspace_id in ['workspace-a']"
    with pytest.raises(ValueError, match="workspace_ids"):
        vector.build_metadata_filter(workspace_ids=[])


def test_milvus_sparse_search_uses_database_bm25_without_sparse_model(monkeypatch):
    vector = MilvusVectorClient(dense=object())
    captured = {}

    class Client:
        def search(self, collection_name, **kwargs):
            captured["collection_name"] = collection_name
            captured.update(kwargs)
            return []

    monkeypatch.setattr(vector, "_client", lambda: Client())
    with app_collection("acme"):
        vector.search_sparse("酒店接机", 5, "")

    assert vector.supports_sparse_vector() is True
    assert captured["data"] == ["酒店接机"]
    assert captured["anns_field"] == "sparse_vector"
    assert captured["search_params"] == {"metric_type": "BM25", "params": {}}


def test_milvus_bm25_can_be_disabled():
    vector = MilvusVectorClient(dense=object(), bm25=False)

    assert vector.supports_sparse_vector() is False
    assert "sparse_vector" not in dict(vector._index_specs())


def test_qdrant_search_uses_server_bm25_when_enabled(monkeypatch):
    vector = QdrantVectorClient(dense=object(), bm25=True)
    captured = {}

    class Client:
        def query_points(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"points": []})()

    monkeypatch.setattr(vector, "_client", lambda: Client())
    with app_collection("acme"):
        vector.search_sparse("酒店接机", 5, None)

    assert vector.supports_sparse_vector() is True
    assert captured["using"] == "bm25"
    assert captured["query"].model == "qdrant/bm25"
    assert captured["query"].options["tokenizer"] == "multilingual"


def test_qdrant_bm25_can_be_disabled():
    vector = QdrantVectorClient(dense=object(), bm25=False)

    assert vector.supports_sparse_vector() is False
    assert qdrant._qdrant_bm25_config(vector.bm25) is None


def test_qdrant_search_filter_scopes_files_and_workspaces():
    vector = QdrantVectorClient(dense=object())

    metadata_filter = vector.build_metadata_filter(["file-a"], ["workspace-a", "workspace-b"])
    assert [(item.key, item.match.any) for item in metadata_filter.must] == [
        ("metadata.file_id", ["file-a"]),
        ("metadata.workspace_id", ["workspace-a", "workspace-b"]),
    ]
    with pytest.raises(ValueError, match="workspace_ids"):
        vector.build_metadata_filter(workspace_ids=[])


def test_milvus_chunk_list_filters_by_workspace_ids(monkeypatch):
    vector = MilvusVectorClient(dense=object())
    captured = {}

    class Client:
        def query(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(vector, "_client", lambda: Client())
    with app_collection("acme"):
        vector.list_chunks(file_ids=["file-a"], workspace_ids=["workspace-a", "workspace-b"])

    assert "file_id in ['file-a']" in captured["filter"]
    assert "workspace_id in ['workspace-a', 'workspace-b']" in captured["filter"]


def test_qdrant_chunk_list_filters_by_workspace_ids(monkeypatch):
    vector = QdrantVectorClient(dense=object())
    captured = {}

    class Client:
        def scroll(self, **kwargs):
            captured.update(kwargs)
            return [], None

    monkeypatch.setattr(vector, "_client", lambda: Client())
    with app_collection("acme"):
        vector.list_chunks(file_ids=["file-a"], workspace_ids=["workspace-a", "workspace-b"])

    assert [(item.key, item.match.any) for item in captured["scroll_filter"].must] == [
        ("metadata.file_id", ["file-a"]),
        ("metadata.workspace_id", ["workspace-a", "workspace-b"]),
    ]


def test_vector_clients_read_routed_dense_dimension_per_request():
    dense = RoutedDense()
    qdrant = QdrantVectorClient(dense=dense)
    milvus = MilvusVectorClient(dense=dense)

    assert qdrant._get_dense_vector_size() == 768
    assert milvus._dense_vector_size() == 768

    dense.vector_size = 1024

    assert qdrant._get_dense_vector_size() == 1024
    assert milvus._dense_vector_size() == 1024
