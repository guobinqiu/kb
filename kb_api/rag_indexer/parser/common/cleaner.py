from __future__ import annotations

import re

from kb_api.rag_indexer.parser.common.schema import Block, TableBlock, TextBlock


def clean_parser_blocks(blocks: list[Block], *, text_separator: str | None = None) -> list[Block]:
    merged = _merge_consecutive_text_blocks(blocks, text_separator=text_separator)
    table_text_by_page = _table_text_by_page(merged)
    return [block for block in merged if not _is_duplicate_table_text(block, table_text_by_page)]


def _merge_consecutive_text_blocks(blocks: list[Block], *, text_separator: str | None = None) -> list[Block]:
    merged: list[Block] = []
    buffer: TextBlock | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer is not None:
            merged.append(buffer)
            buffer = None

    for block in blocks:
        if isinstance(block, TextBlock):
            if buffer is not None and buffer.page == block.page and buffer.kind == block.kind == "text":
                buffer = TextBlock(_join_text(buffer.text, block.text, text_separator), page=buffer.page, kind="text")
            else:
                flush()
                buffer = block
            continue
        flush()
        merged.append(block)

    flush()
    return merged


def _table_text_by_page(blocks: list[Block]) -> dict[int | None, str]:
    table_text: dict[int | None, list[str]] = {}
    for block in blocks:
        if not isinstance(block, TableBlock):
            continue
        parts = [block.caption]
        parts.extend(cell for row in block.rows for cell in row)
        table_text.setdefault(block.page, []).extend(parts)
    return {page: _compact_for_match("".join(parts)) for page, parts in table_text.items()}


def _is_duplicate_table_text(block: Block, table_text_by_page: dict[int | None, str]) -> bool:
    if not isinstance(block, TextBlock) or block.kind != "text":
        return False
    text = _compact_for_match(block.text)
    if not text:
        return True
    table_text = table_text_by_page.get(block.page) or table_text_by_page.get(None, "")
    return bool(table_text and text in table_text)


def _join_text(left: str, right: str, separator: str | None = None) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if separator is not None:
        return left + separator + right
    if _needs_space(left[-1], right[0]):
        return f"{left} {right}"
    return left + right


def _needs_space(left: str, right: str) -> bool:
    if left in "([{<" or right in ")]}>.,;:!?/，。；：！？、":
        return False
    return bool(re.match(r"[A-Za-z0-9]", left) and re.match(r"[A-Za-z0-9]", right))


def _compact_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text)
