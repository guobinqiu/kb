from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str | None
    service: str | None = None
    retryable: StrictBool
    traceId: str = Field(pattern=r"^[0-9a-f]{32}$")


class Dense(Protocol):
    ready: bool

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @property
    def vector_size(self) -> int:
        ...


class Sparse(Protocol):
    ready: bool

    def embed_query(self, text: str) -> dict[int, float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        ...
