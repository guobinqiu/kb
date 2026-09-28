import re

from kb_api.rag_indexer.parser.common.schema import Block, TextBlock


def normalize_blocks(blocks: list[Block]) -> list[Block]:
    normalized: list[Block] = []

    for block in blocks:
        if isinstance(block, TextBlock):
            text = block.text if block.kind in {"code", "list_item"} else block.text.strip()
            if not text.strip():
                continue
            normalized.append(TextBlock(text, page=block.page, kind=block.kind, level=block.level if block.kind == "heading" else None))
            continue

        normalized.append(block)

    return normalized


def is_section_title_text(text: str) -> bool:
    text = text.strip()
    if "\n" in text or len(text) > 80:
        return False
    return bool(re.match(r"^(\d+[\.\、]|[一二三四五六七八九十]+[、.．]|[A-Z][\).])\s*\S+", text))
