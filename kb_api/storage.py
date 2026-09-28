from __future__ import annotations

from datetime import timedelta
from typing import BinaryIO, Protocol
from urllib.parse import urlsplit


class StorageClient(Protocol):
    def presign_put(self, object_key: str, expires_seconds: int) -> str: ...
    def stat(self, object_key: str): ...
    def object_url(self, object_key: str) -> str: ...
    def delete(self, object_key: str) -> None: ...
    def close(self) -> None: ...


class MinioStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        public_url: str = "http://localhost:9000",
    ):
        from minio import Minio

        self.bucket = bucket
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        public = urlsplit(public_url)
        if public.scheme not in {"http", "https"} or not public.hostname or public.path not in {"", "/"}:
            raise ValueError("KB_MINIO_PUBLIC_URL must be an HTTP(S) origin without a path")
        self.public_endpoint = public.netloc
        self.public_secure = public.scheme == "https"
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
            from minio import Minio

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

    def stat(self, object_key: str):
        return self.client.stat_object(self.bucket, object_key)

    def object_url(self, object_key: str) -> str:
        return f"s3://{self.bucket}/{object_key}"

    def delete(self, object_key: str) -> None:
        self.client.remove_object(self.bucket, object_key)

    def close(self) -> None:
        pass
