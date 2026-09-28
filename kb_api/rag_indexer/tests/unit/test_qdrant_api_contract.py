from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from kb_api.rag_indexer.common.config import StorageConfig
from kb_api.rag_indexer.core.api.schemas import FileIndexRequest, PresignRequest, SearchRequest
from kb_api.rag_indexer.core.auth import Principal


pytestmark = pytest.mark.unit


def test_indexer_search_schema_uses_workspace_ids_without_node_ids():
    request = SearchRequest(query="policy", workspace_ids=["workspace-1", "workspace-2"])

    assert request.workspace_ids == ["workspace-1", "workspace-2"]
    with pytest.raises(ValueError):
        SearchRequest(query="policy", node_ids=["node-1"])


def test_index_file_indexes_presigned_file_without_database(monkeypatch):
    from kb_api.rag_indexer.core.api.services import files as service

    class VectorClient:
        def app_scope(self, app_id):
            from contextlib import nullcontext
            return nullcontext()

        def app_collection_exists(self, app_id):
            return True

    state = FastAPI().state
    state.ready = True
    state.vector_client = VectorClient()
    state.config = SimpleNamespace(storage=StorageConfig(endpoint_url="http://minio:9000"))
    monkeypatch.setattr(service, "resolve_embedding", lambda *args: None)
    monkeypatch.setattr(service, "embedding_scope", lambda state, spec: __import__("contextlib").nullcontext())
    monkeypatch.setattr(service, "_resolve_presigned_url", lambda *args: "https://source/a.txt")
    monkeypatch.setattr(service, "index_presigned_file", lambda *args, **kwargs: (2, 5))

    result = service.index_file(
        state,
        FileIndexRequest(s3_url="s3://rag/docs/a.txt", filename="a.txt", file_id="file-a"),
        Principal(type="app", app_id="imsdom"),
    )

    assert result["success"] is True
    assert result["file_id"] == "file-a"
    assert result["chunk_count"] == 2


def test_storage_presign_uses_minio_endpoint(monkeypatch):
    from datetime import timedelta
    from kb_api.rag_indexer.core.api.services import files as service

    class FakeMinio:
        def __init__(self, endpoint, *, access_key, secret_key, secure):
            assert endpoint == "minio:9000"
            assert access_key == "dummy-access-key"
            assert secret_key == "dummy-secret-key"
            assert secure is False

        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag"
            assert object_name == "docs/a.pdf"
            assert expires == timedelta(seconds=120)
            return "http://minio:9000/rag/docs/a.pdf?token=abc"

    monkeypatch.setattr(service, "Minio", FakeMinio)
    monkeypatch.setenv("S3_ACCESS_KEY", "dummy-access-key")
    monkeypatch.setenv("S3_SECRET_KEY", "dummy-secret-key")
    state = SimpleNamespace(config=SimpleNamespace(storage=StorageConfig(endpoint_url="http://minio:9000")))

    result = service.presign_object(state, PresignRequest(s3_url="s3://rag/docs/a.pdf", expires_in=120))

    assert result == {"presigned_url": "http://minio:9000/rag/docs/a.pdf?token=abc"}


def test_routes_only_expose_indexer_file_operations():
    from kb_api.rag_indexer.app import main

    paths = {route.path for route in main.app.routes}

    assert "/api/v1/rag/files" in paths
    assert "/api/v1/rag/presign" in paths
    assert "/api/v1/rag/apps/{app_id}/chunks/{chunk_id}/dense-vector" in paths
    assert "/api/rag/files" not in paths
    assert "/api/rag/upload" not in paths
    assert "/api/rag/chunks" not in paths


def test_client_delete_file_removes_vector_chunks_only(monkeypatch):
    from kb_api.rag_indexer.core.api.services import files as service

    class VectorClient:
        def app_collection_exists(self, app_id):
            return True

        def delete_file_chunks(self, file_id):
            assert file_id == "file-a"
            return 2

    state = SimpleNamespace(ready=True, vector_client=VectorClient())
    result = service.client_delete_file(state, "file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
