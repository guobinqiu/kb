"""rag/__init__.py: 包入口。

显式 re-export 公共 API，方便测试与外部 import：
    from chat.src.rag.client import RagClient, RagResult, get_rag_client
    from chat.src.rag.schemas import SearchRequest, SearchResponse, Document
"""

from __future__ import annotations

from chat.src.rag.client import (
    RAG_DEFAULT_TOP_K,
    RagClient,
    RagResult,
    get_rag_client,
)
from chat.src.rag.schemas import Document, SearchRequest, SearchResponse

__all__ = [
    "RAG_DEFAULT_TOP_K",
    "RagClient",
    "RagResult",
    "get_rag_client",
    "SearchRequest",
    "SearchResponse",
    "Document",
]
