import re
from html import unescape
from html.parser import HTMLParser

from kb_api.rag_indexer.parser.common.normalizer import is_section_title_text
from kb_api.rag_indexer.parser.common.schema import Block, TableBlock, TextBlock


def compact_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def html_table_to_rows(html: str) -> list[list[str]]:
    parser = _HTMLTableParser()
    parser.feed(html)
    if not parser.rows:
        return []

    width = max(len(row) for row in parser.rows)
    rows = [row + [""] * (width - len(row)) for row in parser.rows]
    non_empty_columns = [index for index in range(width) if any(row[index] for row in rows)]
    if non_empty_columns:
        rows = [[row[index] for index in non_empty_columns] for row in rows]
    return rows


def table_html_to_blocks(html: str, title: str = "", page: int | None = None) -> list[Block]:
    return table_rows_to_blocks(title, html_table_to_rows(html), page=page)


def table_rows_to_blocks(
    title: str,
    rows: list[list[str]],
    page: int | None = None,
) -> list[Block]:
    if not rows:
        return []
    blocks = []
    for block_type, logical_title, header, body in _split_logical_tables(title, rows):
        if block_type == "text":
            text = clean_table_text(logical_title).strip()
            if text:
                blocks.append(TextBlock(text, page=page))
            continue
        rows = [[clean_table_text(cell).strip() for cell in row] for row in [header, *body]]
        width = max(len(row) for row in rows)
        columns = [index for index in range(width) if any(index < len(row) and row[index] for row in rows)]
        rows = [[row[index] if index < len(row) else "" for index in columns] for row in rows]
        blocks.append(TableBlock(rows=rows, caption=logical_title, page=page))
    return blocks


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def clean_table_text(text: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", text)


def _split_logical_tables(title: str, rows: list[list[str]]) -> list[tuple[str, str, list[str], list[list[str]]]]:
    if len(rows) >= 2 and _is_section_title_row(rows[0]):
        title = "\n".join(part for part in (title, _row_text(rows[0])) if part)
        rows = rows[1:]

    header = rows[0]
    body = rows[1:]
    if not body:
        return [("table", title, [f"列{index + 1}" for index in range(len(header))], [header])]

    tables: list[tuple[str, str, list[str], list[list[str]]]] = []
    current_title = title
    current_header = header
    current_rows: list[list[str]] = []
    index = 0
    while index < len(body):
        row = body[index]
        next_row = body[index + 1] if index + 1 < len(body) else None
        if current_rows and _is_section_title_row(row) and next_row is not None and _is_header_row(next_row):
            tables.append(("table", current_title, current_header, current_rows))
            tables.append(("text", _row_text(row), [], []))
            current_title = ""
            current_header = next_row
            current_rows = []
            index += 2
            continue
        current_rows.append(row)
        index += 1

    if current_rows:
        tables.append(("table", current_title, current_header, current_rows))
    return tables


def _is_section_title_row(row: list[str]) -> bool:
    cells = [cell for cell in row if cell.strip()]
    if len(cells) != 1:
        return False
    return is_section_title_text(cells[0])


def _is_header_row(row: list[str]) -> bool:
    return sum(1 for cell in row if cell.strip()) >= 2


def _row_text(row: list[str]) -> str:
    return " ".join(cell.strip() for cell in row if cell.strip())


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(compact_cell_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
