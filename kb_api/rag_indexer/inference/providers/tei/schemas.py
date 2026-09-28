from __future__ import annotations

from typing import Annotated

from pydantic import Field, TypeAdapter
from pydantic import BaseModel


class _EmbeddingRow(BaseModel):
    index: Annotated[int, Field(ge=0)]
    embedding: list[Annotated[float, Field(allow_inf_nan=False)]] = Field(min_length=1)


class _EmbeddingResponse(BaseModel):
    data: list[_EmbeddingRow]


class _RerankRow(BaseModel):
    index: Annotated[int, Field(ge=0)]
    score: Annotated[float, Field(allow_inf_nan=False)]


_RerankRowsAdapter = TypeAdapter(list[_RerankRow])
