from types import SimpleNamespace
from urllib.parse import urlsplit

from minio import Minio

from kb_api.storage import MinioStorage


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
