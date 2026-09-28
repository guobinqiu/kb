from __future__ import annotations

from typing import Protocol
from contextlib import AbstractContextManager


SearchMode = str


class VectorClient(Protocol):
    backend_name: str
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def drop_collections(self) -> None:
        ...

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        ...

    def delete_file_chunks(self, file_id: str) -> int:
        ...

    def delete_stale_file_chunks(self, file_id: str, keep_count: int) -> int:
        ...

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        ...

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> dict:
        ...

    def get_dense_vector(self, chunk_id: str) -> list[float] | None:
        ...

    def supports_dense_vector(self) -> bool:
        ...

    def supports_sparse_vector(self) -> bool:
        ...

    def ensure_app_collection(self, app_id: str) -> str:
        ...

    def app_collection_exists(self, app_id: str) -> bool:
        ...

    def drop_app_collection(self, app_id: str) -> bool:
        ...

    def app_scope(self, app_id: str) -> AbstractContextManager:
        ...

    def build_file_filter(self, file_ids: list[str] | None = None):
        ...

    def encode_dense_query(self, query: str):
        ...

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_dense(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def encode_sparse_query(self, query: str):
        ...

    def query_sparse_vector(self, query_vector, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_sparse(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...
