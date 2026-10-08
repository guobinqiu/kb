from __future__ import annotations

from typing import Protocol
from contextlib import AbstractContextManager


class VectorClient(Protocol):
    backend_name: str
    ready: bool

    def close(self) -> None:
        ...

    def list_chunks(self, file_ids: list[str] | None = None, limit: int = 50, cursor: str | None = None, workspace_ids: list[str] | None = None) -> dict:
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

    def build_metadata_filter(self, file_ids: list[str] | None = None, workspace_ids: list[str] | None = None):
        ...

    def encode_dense_query(self, query: str):
        ...

    def query_dense_vector(self, query_vector, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_dense(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_sparse(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...
