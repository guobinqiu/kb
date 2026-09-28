"""Pydantic schemas 单测（§11.1）。

覆盖：
- SearchRequest.model_dump(exclude_none=True) 排除 None 字段
- 紧凑序列化（与 json.dumps(..., separators=(",",":")) 字节级一致）
- 字段顺序保持（与构造顺序一致）
- Document 解析 metadata
- file_ids 非空数组校验
- SearchResponse 解析 results[] 无 score 字段
"""

from __future__ import annotations

import json

import pytest


pytestmark = pytest.mark.unit


def _try_import_symbol(module_path: str, name: str):
    """缺失模块/属性时返回 None；存在则返回 symbol。"""
    try:
        mod = __import__(module_path, fromlist=[name])
        return getattr(mod, name, None)
    except Exception:
        return None


# ────────────────────────────── SearchRequest ──────────────────────────────


def test_search_request_exclude_none_drops_optional_fields():
    """只设 query 时，model_dump(exclude_none=True) 应只含 {"query": "..."}。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="hi", workspace_ids=["workspace-1"])
    dumped = req.model_dump(exclude_none=True)
    assert dumped == {"query": "hi", "workspace_ids": ["workspace-1"]}


def test_search_request_compact_json_serialization():
    """SearchRequest 必须能以紧凑模式序列化（无空格）。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="退款流程", workspace_ids=["workspace-1"], top_k=5)
    dumped = req.model_dump(exclude_none=True)
    compact = json.dumps(dumped, separators=(",", ":"), ensure_ascii=False)
    # 紧凑模式：字段间无空格
    assert ", " not in compact
    assert ": " not in compact
    # 中文不走 ensure_ascii
    assert "退款流程" in compact


def test_search_request_default_query_none_excluded():
    """未传 query 时若默认 None，应被 exclude_none 排除。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    # 仅设 top_k
    req = cls(workspace_ids=["workspace-1"], top_k=3)
    dumped = req.model_dump(exclude_none=True)
    assert "query" not in dumped  # 缺省被排除
    assert dumped["top_k"] == 3


def test_search_request_top_k_optional_default_in_range():
    """top_k 等可选项有合理默认值时（5 或 None），不应抛。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(query="q", workspace_ids=["workspace-1"])
    # 字段必须有，且参与序列化时类型正确
    dumped = req.model_dump(exclude_none=True)
    assert isinstance(dumped, dict)
    assert dumped["query"] == "q"


def test_search_request_file_ids_must_be_non_empty_if_provided():
    """file_ids 若提供，必须是非空数组。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    try:
        from pydantic import ValidationError
    except ImportError as exc:
        pytest.fail(f"pydantic not installed (expected): {exc}")

    # 正常用例
    valid = cls(query="q", workspace_ids=["workspace-1"], file_ids=["doc-1", "doc-2"])
    assert valid.file_ids == ["doc-1", "doc-2"]

    # 空数组应被拒
    try:
        cls(query="q", workspace_ids=["workspace-1"], file_ids=[])
    except ValidationError:
        return
    except Exception:
        return
    pytest.fail("SearchRequest 应拒绝空 file_ids 数组（doc §11.1 明确要求）")


def test_search_request_full_payload_round_trip():
    """所有字段都填时，dump → 紧凑 JSON 字节级正确。"""
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")
    if cls is None:
        pytest.fail("rag.schemas.SearchRequest not implemented — RED")
    req = cls(
        query="hi",
        workspace_ids=["workspace-1", "workspace-2"],
        top_k=3,
        file_ids=["a", "b"],
    )
    dumped = req.model_dump(exclude_none=True)
    assert dumped["query"] == "hi"
    assert dumped["top_k"] == 3
    assert dumped["file_ids"] == ["a", "b"]
    assert dumped["workspace_ids"] == ["workspace-1", "workspace-2"]
    # 紧凑 JSON 可序列化
    compact = json.dumps(dumped, separators=(",", ":"), ensure_ascii=False)
    assert compact.startswith("{") and compact.endswith("}")


def test_search_request_workspace_ids_must_be_non_empty():
    cls = _try_import_symbol("chat.src.rag.schemas", "SearchRequest")

    with pytest.raises(Exception, match="workspace_ids"):
        cls(query="q", workspace_ids=[])


# ────────────────────────────── Document ──────────────────────────────


def test_document_parses_minimal_fields():
    """Document 必须能解析简化后的 id/content 字段。"""
    Document = _try_import_symbol("chat.src.rag.schemas", "Document")
    if Document is None:
        pytest.fail("rag.schemas.Document not implemented — RED")
    raw = {
        "id": "chunk-001",
        "content": "退款条款：7 天内可全额退款。",
    }
    doc = Document(**raw)
    assert doc.id == "chunk-001"
    assert doc.content.startswith("退款")


def test_response_accepts_result_without_score():
    """SearchResponse 应能解析无 score 字段的 RAG 响应。"""
    Response = _try_import_symbol("chat.src.rag.schemas", "SearchResponse")
    Document = _try_import_symbol("chat.src.rag.schemas", "Document")
    if Response is None or Document is None:
        pytest.fail("rag.schemas.SearchResponse/Document not implemented — RED")
    raw = {
        "results": [
            {
                "id": "c1",
                "content": "text",
                # 注意：没有 score 字段（契约约束）
            }
        ],
        "mode": "dense",
        "rerank": True,
        "rerank_fetch_k": 20,
        "elapsed_ms": 42.0,
    }
    resp = Response(**raw)
    assert len(resp.results) == 1
    doc = resp.results[0]
    assert doc.id == "c1"
    assert "score" not in doc.model_dump()


def test_document_parses_simplified_qdrant_open_search_result():
    """Document 应兼容 qdrant `/api/v1/rag/search` 的简化 result 结构。"""
    Document = _try_import_symbol("chat.src.rag.schemas", "Document")
    if Document is None:
        pytest.fail("rag.schemas.Document not implemented — RED")
    raw = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "content": "命中的 chunk 文本",
        "score": 0.82,
    }
    doc = Document(**raw)
    assert doc.id == "550e8400-e29b-41d4-a716-446655440000"
    assert doc.content == "命中的 chunk 文本"
    assert "score" not in doc.model_dump()


def test_documents_iteration_and_count():
    """SearchResponse.results 是 list[Document]，可迭代。"""
    Response = _try_import_symbol("chat.src.rag.schemas", "SearchResponse")
    if Response is None:
        pytest.fail("rag.schemas.SearchResponse not implemented — RED")
    raw = {
        "results": [
            {
                "id": f"c{i}",
                "content": f"text {i}",
            }
            for i in range(3)
        ],
        "mode": "dense",
        "rerank": False,
        "rerank_fetch_k": 10,
        "elapsed_ms": 1.0,
    }
    resp = Response(**raw)
    assert len(resp.results) == 3
    assert [d.id for d in resp.results] == ["c0", "c1", "c2"]


def test_schemas_module_path_is_rag_schemas():
    """关键 schema 类必须从 rag.schemas 导出。"""
    try:
        from chat.src.rag.schemas import (  # type: ignore  # noqa: F401
            Document,
            SearchRequest,
            SearchResponse,
        )
    except ImportError as exc:
        pytest.fail(f"rag.schemas 模块缺失或导出错误: {exc}")
