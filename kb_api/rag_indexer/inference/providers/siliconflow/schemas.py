from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class _EmbeddingRow(BaseModel):
    index: Annotated[int, Field(ge=0)]
    embedding: list[Annotated[float, Field(allow_inf_nan=False)]] = Field(min_length=1)


class _EmbeddingResponse(BaseModel):
    status: Literal["completed"] = "completed"
    data: list[_EmbeddingRow]


class _RerankRow(BaseModel):
    index: Annotated[int, Field(ge=0)]
    relevance_score: Annotated[float, Field(allow_inf_nan=False)]


class _RerankResponse(BaseModel):
    status: Literal["completed"] = "completed"
    results: list[_RerankRow]
