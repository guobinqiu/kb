from types import SimpleNamespace
from urllib.parse import urlsplit
import hashlib
import io

import pytest

from minio import Minio

from kb_api.api.services.minio import MinioStorage


def test_presign_put_uses_internal_endpoint_for_region_lookup(monkeypatch):
    contacted = []

    def region_response(client, *_args, **_kwargs):
        host = client._base_url._url.netloc
        contacted.append(host)
        if host != "minio:9000":
            raise AssertionError(f"region lookup used public endpoint: {host}")
        return SimpleNamespace(data=b"<LocationConstraint>us-east-1</LocationConstraint>")

    monkeypatch.setattr(Minio, "_url_open", region_response)
    storage = MinioStorage(
        "minio:9000", "access", "secret", "kb-files", public_url="http://localhost:9000"
    )

    url = storage.presign_put("uploads/report.txt", expires_seconds=900)

    assert urlsplit(url).netloc == "localhost:9000"
    assert urlsplit(url).path == "/kb-files/uploads/report.txt"
    assert contacted == ["minio:9000"]


def test_checksum_hashes_object_content_and_closes_response(monkeypatch):
    storage = MinioStorage("minio:9000", "access", "secret", "kb-files")
    response = io.BytesIO(b"document content")
    released = []
    response.release_conn = lambda: released.append(True)
    requested = []

    def get_object(bucket, key):
        requested.append((bucket, key))
        return response

    monkeypatch.setattr(storage.client, "get_object", get_object)
    assert storage.checksum("s3://kb-files/uploads/a.txt") == hashlib.sha256(b"document content").hexdigest()
    assert requested == [("kb-files", "uploads/a.txt")]
    assert response.closed
    assert released == [True]


def test_storage_rejects_url_outside_its_bucket():
    storage = MinioStorage("minio:9000", "access", "secret", "kb-files")
    with pytest.raises(ValueError):
        storage.stat("s3://other/uploads/a.txt")
