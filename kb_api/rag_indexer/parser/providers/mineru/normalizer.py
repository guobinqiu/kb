import json
from pathlib import Path

from markdown_it import MarkdownIt

from kb_api.rag_indexer.parser.common.cleaner import clean_parser_blocks
from kb_api.rag_indexer.parser.common.normalizer import is_section_title_text
from kb_api.rag_indexer.parser.common.schema import Block, FormulaBlock, TableBlock, TextBlock
from kb_api.rag_indexer.parser.common.table_blocks import (
    clean_table_text,
    compact_cell_text,
    html_table_to_rows,
    strip_html_tags,
    table_rows_to_blocks,
)


def read_content_list_blocks(output_dir: Path) -> list[Block]:
    json_files = sorted(output_dir.rglob("*_content_list.json"))
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        blocks = content_list_to_blocks(data)
        if blocks:
            return blocks
    return []


def structured_content_to_blocks(data: dict) -> list[Block]:
    items = []
    for page in data["pages"]:
        for block in page["blocks"]:
            item = {**block, "page_idx": page["page_idx"]}
            if "bbox" in block:
                # Structured content uses 0..1; content list uses 0..1000.
                item["bbox"] = [value * 1000 for value in block["bbox"]]
            content = block.get("content", "")
            if block["type"] in {"doc_title", "paragraph_title"}:
                item["text_level"] = block.get("level") or 1
            elif block["type"] == "table":
                markdown = MarkdownIt("commonmark").enable("table")
                tokens = markdown.parse(content)
                if len(tokens) == 1 and tokens[0].type == "fence":
                    tokens = markdown.parse(tokens[0].content)
                item["table_body"] = markdown.renderer.render(tokens, markdown.options, {})
                item["table_caption"] = [caption["content"] for caption in block.get("captions", [])]
            elif block["type"] == "list":
                item["list_items"] = [content]
            elif block["type"] == "code":
                tokens = MarkdownIt().parse(content)
                item["code_body"] = tokens[0].content if len(tokens) == 1 and tokens[0].type == "fence" else content
            items.append(item)
    return content_list_to_blocks(items)


def content_list_to_blocks(data) -> list[Block]:
    if not isinstance(data, list):
        return []
    blocks = []
    previous_table = None
    for item in data:
        if not isinstance(item, dict):
            previous_table = None
            continue
        if item.get("type") == "table":
            rows = _table_item_rows(item)
            has_rows = bool(rows)
            caption = _text_value(item.get("table_caption"))
            if blocks and isinstance(blocks[-1], TableBlock) and not caption and _cross_page_boundary(previous_table, item):
                # Cloud results can leave empty placeholders for pages already included in the preceding table.
                if not rows:
                    previous_table = item
                    continue
                end = next((index for index, row in enumerate(rows) if _section_row(row)), len(rows))
                continuation = rows[:end]
                header = blocks[-1].rows[0]
                width = len(header)
                if continuation and width and all(len(row) >= width and not any(row[width:]) for row in continuation):
                    continuation = [[clean_table_text(cell).strip() for cell in row[:width]] for row in continuation]
                    first = continuation[0]
                    if first == header or first[0] != header[0]:
                        blocks[-1].rows.extend(continuation[1:] if first == header else continuation)
                        rows = rows[end:]
            blocks.extend(table_rows_to_blocks(caption, rows, page=_mineru_page(item)))
            previous_table = item if has_rows else None
            continue
        previous_table = None
        blocks.extend(_content_item_to_blocks(item))
    return clean_parser_blocks(blocks)


def _section_row(row: list[str]) -> bool:
    cells = [cell for cell in row if cell.strip()]
    return len(cells) == 1 and is_section_title_text(cells[0])


def _cross_page_boundary(previous: dict | None, current: dict) -> bool:
    if previous is None:
        return False
    previous_page = _mineru_page(previous)
    current_page = _mineru_page(current)
    if previous_page is None or current_page != previous_page + 1:
        return False
    left = previous.get("bbox")
    right = current.get("bbox")
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != 4 or len(right) != 4:
        return False
    if not all(isinstance(value, (int, float)) for value in left + right):
        return False
    # MinerU content-list boxes use 0..1000 page coordinates. Only join aligned page-edge fragments.
    return left[3] >= 850 and right[1] <= 150 and abs(left[0] - right[0]) <= 20 and abs(left[2] - right[2]) <= 20


def _content_item_to_blocks(item: dict) -> list[Block]:
    item_type = item.get("type")
    if item_type in {"image", "chart"}:
        return []
    if item_type == "list":
        return [TextBlock(text.strip(), page=_mineru_page(item), kind="list_item")
                for text in item.get("list_items", []) if text.strip()]
    if item_type == "code":
        text = str(item.get("code_body") or "").rstrip("\r\n")
        return [TextBlock(text, page=_mineru_page(item), kind="code")] if text.strip() else []
    if item_type in {"equation", "interline_equation"}:
        text = clean_table_text(_text_value(item.get("text") or item.get("content")))
        return [FormulaBlock(text, format=str(item.get("text_format") or "latex"), page=_mineru_page(item))] if text else []

    text = clean_table_text(_text_value(item.get("text") or item.get("content")))
    if not text:
        return []
    kind = "heading" if item.get("text_level") else "text"
    level = item.get("text_level")
    level = level if type(level) is int and level > 0 else None
    return [TextBlock(text, page=_mineru_page(item), kind=kind, level=level)]


def _table_item_rows(item: dict) -> list[list[str]]:
    table_body = item.get("table_body") or item.get("html")
    if isinstance(table_body, str) and table_body.strip():
        return html_table_to_rows(table_body)
    rows = item.get("rows")
    if not isinstance(rows, list):
        return []
    normalized_rows = []
    for row in rows:
        if isinstance(row, list):
            normalized_rows.append([compact_cell_text(str(cell)) for cell in row])
    return normalized_rows


def _mineru_page(item: dict) -> int | None:
    page_idx = item.get("page_idx")
    return int(page_idx) + 1 if page_idx is not None else None


def _text_value(value) -> str:
    if isinstance(value, str):
        return strip_html_tags(value).strip()
    if isinstance(value, list):
        return " ".join(_text_value(item) for item in value if item).strip()
    return ""
