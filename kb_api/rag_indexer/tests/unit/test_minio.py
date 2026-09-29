from datetime import timedelta
from types import SimpleNamespace

import pytest

from kb_api.rag_indexer.clients import minio as storage
from kb_api.rag_indexer.common.config import StorageConfig
from kb_api.rag_indexer.index_tasks import _presigned_url


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("entrypoint,expires_in", [("storage", 120), ("mq", 3600)])
def test_storage_presign_uses_minio_endpoint(monkeypatch, entrypoint, expires_in):

    class FakeMinio:
        def __init__(self, endpoint, *, access_key, secret_key, secure):
            assert endpoint == "minio:9000"
            assert access_key == "dummy-access-key"
            assert secret_key == "dummy-secret-key"
            assert secure is False

        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag"
            assert object_name == "uploads/imsdom/docs/a.pdf"
            assert expires == timedelta(seconds=expires_in)
            return "http://minio:9000/rag/docs/a.pdf?token=abc"

    monkeypatch.setattr(storage, "Minio", FakeMinio)
    monkeypatch.setenv("S3_ACCESS_KEY", "dummy-access-key")
    monkeypatch.setenv("S3_SECRET_KEY", "dummy-secret-key")
    state = SimpleNamespace(config=SimpleNamespace(storage=StorageConfig(endpoint_url="http://minio:9000")))

    s3_url = "s3://rag/uploads/imsdom/docs/a.pdf"
    if entrypoint == "mq":
        result = _presigned_url(state, s3_url)
    else:
        result = storage.presign_object(state.config.storage, s3_url, expires_in=expires_in)

    assert result == "http://minio:9000/rag/docs/a.pdf?token=abc"
