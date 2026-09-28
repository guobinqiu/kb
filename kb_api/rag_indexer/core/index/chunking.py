from __future__ import annotations

import re
import uuid
from html import unescape
from pathlib import Path

from kb_api.rag_indexer.core.index.text_splitter import split_text as _split_text

from kb_api.rag_indexer.common.config import ChunkingConfig


def parser_blocks_to_chunks(blocks: list[dict], filename: str, config: ChunkingConfig) -> list[dict]:
    chunks = []
    normalized = [_normalize_block(block) for block in blocks]
    pending = ""
    has_body = False
    page = None
    suffix = Path(filename).suffix.lower()

    def flush():
        nonlocal pending, has_body
        if pending:
            # 读取闭包变量 page：循环开头的 flush 发生在 page 赋值前，pending 属于上一页，保留旧页正确
            chunks.append(_document(pending, filename, page))
            pending = ""
        has_body = False

    for block in normalized:
        # 仅当 pending 含正文时才因翻页 flush；纯标题 pending 允许跨页挂靠下一页内容
        # （如页尾标题 + 下页表格），避免标题被切成无检索价值的孤块
        if page != block.get("page") and has_body:
            flush()
        page = block.get("page")
        if block["type"] == "text":
            if suffix == ".txt":
                flush()
                chunks.extend(_text_documents(block["text"], filename, config, block.get("page")))
                continue
            kind = block["kind"]
            if kind == "heading" and has_body:
                flush()
            text = block["text"]
            if not text.strip():
                continue
            separator = "\n" if kind == "list_item" else "\n\n"
            if pending and len(pending) + len(separator) + len(text) <= config.text.chunk_size:
                pending += separator + text
                has_body = has_body or kind != "heading"
                continue
            available = config.text.chunk_size - len(pending) - len(separator)
            if pending and not has_body and kind not in {"heading", "code"} and available > 0:
                first = _split_text(text, available, 0)[0]
                pending += separator + first
                text = text[len(first):].lstrip()
            flush()
            parts = [text] if kind == "code" or len(text) <= config.text.chunk_size else _split_text(text, config.text.chunk_size, config.text.chunk_overlap)
            chunks.extend(_document(part, filename, page) for part in parts[:-1])
            pending = parts[-1] if parts else ""
            has_body = kind != "heading"
            continue
        if block["type"] == "table":
            caption = block["caption"]
            if pending and not has_body:
                heading_text = pending
                pending = ""
                if caption and caption.strip() not in heading_text:
                    # caption 含独立信息（表N/年份等）→ 两者都保留
                    caption = heading_text + "\n" + caption
                else:
                    # caption 缺失或只是标题的复述（子串）→ 只保留 heading 一份
                    caption = heading_text
            flush()
            # 表格吸收前一个相邻文本 chunk 的 content 作为前缀（原文本 chunk 保留，
            # 接受索引中重复一份），让表格可通过上下文文本两路检索；连续表格不互相吸收
            prefix = ""
            if chunks and chunks[-1]["metadata"].get("block_type") != "table":
                prefix = chunks[-1]["content"]
            table_text = (prefix + "\n" if prefix else "") + _render_table_text(block["rows"], caption)
            chunk = _document(table_text, filename, block.get("page"))
            chunk["metadata"]["block_type"] = "table"
            chunks.append(chunk)
            continue
        flush()
        if block["type"] == "formula":
            chunks.extend(_text_documents(block["text"], filename, config, block.get("page")))
    flush()
    for chunk_index, chunk in enumerate(chunks):
        chunk["metadata"]["chunk_index"] = chunk_index
    return chunks


def _normalize_block(block: dict) -> dict:
    block_type = block.get("type")
    if block_type == "text":
        kind = block.get("kind", "text")
        text = block["text"] if kind in {"code", "list_item"} else block["text"].strip()
        return {"type": "text", "text": text, "kind": kind, "page": block.get("page")}
    if block_type == "table":
        rows = _normalize_table_rows(block["rows"])
        caption = str(block.get("caption") or "").strip()
        return {"type": "table", "caption": caption, "rows": rows, "page": block.get("page")}
    if block_type == "formula":
        return {"type": "formula", "text": str(block.get("text") or "").strip(), "format": str(block.get("format") or "latex"), "page": block.get("page")}
    raise ValueError(f"Unsupported parser block type: {block_type}")


def _text_documents(text: str, filename: str, config: ChunkingConfig, page: int | None = None) -> list[dict]:
    if not text:
        return []
    paragraphs = re.split(r"\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*", text) if Path(filename).suffix.lower() == ".txt" else [text]
    return [
        _document(chunk.strip(), filename, page)
        for paragraph in paragraphs
        for chunk in _split_text(paragraph, config.text.chunk_size, config.text.chunk_overlap)
        if chunk.strip()
    ]


def _document(content: str, filename: str, page: int | None = None) -> dict:
    metadata = {}
    if filename:
        metadata["filename"] = filename
    if page is not None:
        metadata["page"] = int(page)
    return {"id": str(uuid.uuid4()), "content": content, "metadata": metadata}


def _normalize_table_rows(value) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows = []
    for row in value:
        if isinstance(row, list):
            rows.append([_compact_cell_text(cell) for cell in row])
    return [row for row in rows if any(cell for cell in row)]


def _render_table_text(rows: list[list[str]], caption: str = "") -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        header = [f"列{index + 1}" for index in range(len(rows[0]))]
        body = rows
    else:
        header = rows[0]
        body = rows[1:]
    lines = [caption] if caption else []
    lines.extend(_render_markdown_header(header))
    lines.extend(_render_table_row(header, row) for row in body)
    return "\n".join(line for line in lines if line).strip()


def _render_markdown_header(header: list[str]) -> list[str]:
    width = max(1, len(header))
    header_cells = [_escape_markdown_cell(header[index] if index < len(header) and header[index] else f"列{index + 1}") for index in range(width)]
    separator_cells = ["---"] * width
    return [
        "| " + " | ".join(header_cells) + " |",
        "| " + " | ".join(separator_cells) + " |",
    ]


def _render_table_row(header: list[str], row: list[str]) -> str:
    cells = []
    width = max(len(header), len(row))
    for index in range(width):
        cell = row[index] if index < len(row) else ""
        cells.append(_escape_markdown_cell(cell))
    return "| " + " | ".join(cells) + " |"


def _compact_cell_text(value) -> str:
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def _escape_markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
