from pathlib import Path

from markdown_it import MarkdownIt

from kb_api.rag_indexer.parser.common.base import BlockParser
from kb_api.rag_indexer.parser.common.schema import Block, TextBlock
from kb_api.rag_indexer.parser.common.table_blocks import table_html_to_blocks
from kb_api.rag_indexer.parser.common.text import clean_cjk_spaces


class MdBlockParser(BlockParser):
    def parse(self, filepath: str) -> list[Block]:
        source = Path(filepath).read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        markdown = MarkdownIt("commonmark").enable("table")
        tokens = markdown.parse(source)
        blocks: list[Block] = []
        covered_until = 0
        list_depth = 0
        quote_depth = 0
        for index, token in enumerate(tokens):
            if token.type in {"bullet_list_open", "ordered_list_open", "bullet_list_close", "ordered_list_close"}:
                list_depth += token.nesting
                continue
            if token.type in {"blockquote_open", "blockquote_close"}:
                quote_depth += token.nesting
                continue
            if token.type in {"inline", "list_item_open", "list_item_close"} or token.map is None or token.nesting == -1:
                continue
            if token.map[0] < covered_until:
                continue
            if token.type == "table_open":
                end = next(
                    end for end in range(index + 1, len(tokens))
                    if tokens[end].type == "table_close" and tokens[end].level == token.level
                )
                table = markdown.renderer.render(tokens[index:end + 1], markdown.options, {})
                blocks.extend(table_html_to_blocks(table))
                covered_until = token.map[1]
                continue
            text = "".join(lines[token.map[0]:token.map[1]]).rstrip("\r\n")
            if token.type in {"heading_open", "paragraph_open"} and not list_depth and not quote_depth:
                text = clean_cjk_spaces(text).strip()
            if text:
                kind = {"heading_open": "heading", "paragraph_open": "paragraph",
                        "fence": "code", "code_block": "code"}.get(token.type, "text")
                if token.type == "paragraph_open":
                    if list_depth:
                        kind = "list_item"
                    elif quote_depth:
                        kind = "text"
                blocks.append(TextBlock(text, kind=kind, level=int(token.tag[1:]) if kind == "heading" else None))
                covered_until = token.map[1]
        return blocks
