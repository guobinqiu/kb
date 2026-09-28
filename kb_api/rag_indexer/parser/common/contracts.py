from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str | None
    service: str | None = None
    retryable: StrictBool
    traceId: str = Field(pattern=r"^[0-9a-f]{32}$")


TextKind = Literal["heading", "paragraph", "list_item", "code", "text"]


class ParserTextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str
    kind: TextKind = "text"
    page: int | None = None
    level: int | None = Field(default=None, ge=1, strict=True)


class ParserTableBlock(BaseModel):
    type: Literal["table"] = "table"
    rows: list[list[str]]
    caption: str | None = None
    page: int | None = None


class ParserFormulaBlock(BaseModel):
    type: Literal["formula"] = "formula"
    text: str
    format: str = "latex"
    page: int | None = None


ParserBlock = Annotated[ParserTextBlock | ParserTableBlock | ParserFormulaBlock, Field(discriminator="type")]


class ParseFileResponse(BaseModel):
    blocks: list[ParserBlock]
    file_size: int | None = Field(default=None, ge=0)
