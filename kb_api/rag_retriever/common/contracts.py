from __future__ import annotations

from typing import Protocol

class Dense(Protocol):
    ready: bool

    def embed_query(self, text: str) -> list[float]:
        ...

    @property
    def vector_size(self) -> int:
        ...


class Sparse(Protocol):
    ready: bool

    def embed_query(self, text: str) -> dict[int, float]:
        ...
