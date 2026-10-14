from __future__ import annotations

from datetime import timedelta
import hashlib
from urllib.parse import urlsplit

from minio import Minio


class MinioStorage:
    def __init__(
        self,
        url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_url: str = "http://localhost:9000",
    ):
        self.bucket = bucket
        endpoint, secure = _origin(url, "KB_MINIO_URL")
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.public_endpoint, self.public_secure = _origin(public_url, "KB_MINIO_PUBLIC_URL")
        self.access_key = access_key
        self.secret_key = secret_key
        if self.public_endpoint == endpoint and self.public_secure == secure:
            self.public_client = self.client
        else:
            self.public_client = None

    def initialize(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def presign_put(self, object_key: str, expires_seconds: int = 900) -> str:
        if self.public_client is None:
            self.public_client = Minio(
                self.public_endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.public_secure,
                region=self.client._get_region(self.bucket),
            )
        return self.public_client.presigned_put_object(
            self.bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )

    def _object_key(self, s3_url: str) -> str:
        url = urlsplit(s3_url)
        if url.scheme != "s3" or url.netloc != self.bucket or not url.path.startswith("/") or url.query or url.fragment:
            raise ValueError("s3_url must reference the configured bucket")
        key = url.path[1:]
        if not key:
            raise ValueError("s3_url must reference an object")
        return key

    def stat(self, s3_url: str):
        return self.client.stat_object(self.bucket, self._object_key(s3_url))

    def checksum(self, s3_url: str) -> str:
        response = self.client.get_object(self.bucket, self._object_key(s3_url))
        digest = hashlib.sha256()
        try:
            for data in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(data)
            return digest.hexdigest()
        finally:
            response.close()
            response.release_conn()

    def object_url(self, object_key: str) -> str:
        return f"s3://{self.bucket}/{object_key}"

    def delete(self, s3_url: str) -> None:
        self.client.remove_object(self.bucket, self._object_key(s3_url))

    def close(self) -> None:
        pass


def _origin(url: str, setting: str) -> tuple[str, bool]:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.path not in {"", "/"} or parsed.query or parsed.fragment or
            parsed.username or parsed.password):
        raise ValueError(f"{setting} must be an HTTP(S) origin without a path")
    return parsed.netloc, parsed.scheme == "https"
