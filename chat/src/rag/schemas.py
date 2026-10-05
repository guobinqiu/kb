"""rag.schemas: Pydantic 数据契约（请求 / 响应 / 文档）。

被 rag/client.py 与 rag/tool.py 共用。生成紧凑 JSON body 用于 HTTP 调用。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Document(BaseModel):
    """单条检索结果，保留来源信息供对话引用。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    """RAG search 请求体。

    LLM 只传业务查询参数；检索模式和候选池由 RAG 服务配置决定。
    """

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    workspace_ids: list[str]
    top_k: int | None = None
    rerank: bool | None = None
    file_ids: list[str] | None = None

    @field_validator("workspace_ids")
    @classmethod
    def _validate_workspace_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("workspace_ids must not be empty")
        return v

    @field_validator("file_ids")
    @classmethod
    def _validate_file_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError("file_ids must not be empty when provided")
        return v


class SearchResponse(BaseModel):
    """RAG search 响应体。"""

    model_config = ConfigDict(extra="ignore")

    results: list[Document] = Field(default_factory=list)
    mode: str | None = None
    rerank: bool | None = None
    rerank_fetch_k: int | None = None
    elapsed_ms: float | None = None
