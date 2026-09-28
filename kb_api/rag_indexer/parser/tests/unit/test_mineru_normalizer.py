import pytest

from kb_api.rag_indexer.parser.common.schema import FormulaBlock, TableBlock, TextBlock
from kb_api.rag_indexer.parser.providers.mineru.normalizer import (
    content_list_to_blocks,
    structured_content_to_blocks,
)


def test_structured_content_preserves_types_levels_and_pages():
    blocks = structured_content_to_blocks({"pages": [{"page_idx": 1, "blocks": [
        {"type": "paragraph_title", "level": 2, "content": "Facilities"},
        {"type": "text", "content": "A gym is available."},
        {"type": "list", "content": "- Pool\n- Gym"},
        {"type": "code", "content": "```python\nprint(1)\n```"},
        {"type": "equation", "content": "E=mc^2"},
        {"type": "table", "content": "<table><tr><th>Name</th><th>Hours</th></tr><tr><td>Gym</td><td>24</td></tr></table>",
         "captions": [{"content": "Opening hours"}]},
        {"type": "image", "content": "ignored"},
    ]}]})
    assert blocks == [
        TextBlock("Facilities", page=2, kind="heading", level=2),
        TextBlock("A gym is available.", page=2),
        TextBlock("- Pool\n- Gym", page=2, kind="list_item"),
        TextBlock("print(1)", page=2, kind="code"),
        FormulaBlock("E=mc^2", page=2),
        TableBlock([["Name", "Hours"], ["Gym", "24"]], caption="Opening hours", page=2),
    ]


def test_structured_content_merges_aligned_cross_page_tables():
    blocks = structured_content_to_blocks({"pages": [
        {"page_idx": 0, "blocks": [{"type": "table", "bbox": [0.1, 0.6, 0.9, 0.95],
         "content": "<table><tr><th>Name</th><th>Latency</th></tr><tr><td>A</td><td>1</td></tr></table>"}]},
        {"page_idx": 1, "blocks": [{"type": "table", "bbox": [0.1, 0.05, 0.9, 0.3],
         "content": "<table><tr><td>B</td><td>2</td></tr></table>"}]},
    ]})
    assert blocks == [TableBlock([["Name", "Latency"], ["A", "1"], ["B", "2"]], page=1)]


def test_structured_content_preserves_markdown_tables_and_continuations():
    blocks = structured_content_to_blocks({"pages": [
        {"page_idx": 0, "blocks": [{"type": "table", "bbox": [0.1, 0.6, 0.9, 0.95],
         "content": "| Name | Notes |\n| --- | --- |\n| A | Works |"}]},
        {"page_idx": 1, "blocks": [{"type": "table", "bbox": [0.1, 0.05, 0.9, 0.3],
         "content": "| B | More |\n| --- | --- |"}]},
    ]})
    assert blocks == [TableBlock([["Name", "Notes"], ["A", "Works"], ["B", "More"]], page=1)]


def test_structured_content_preserves_fenced_markdown_table():
    blocks = structured_content_to_blocks({"pages": [{"page_idx": 0, "blocks": [
        {"type": "table", "content": "```\n| Name | Notes |\n| --- | --- |\n| A | Works |\n```"},
    ]}]})
    assert blocks == [TableBlock([["Name", "Notes"], ["A", "Works"]], page=1)]


def _table(rows, page, bbox, caption=None):
    return {"type": "table", "rows": rows, "page_idx": page, "bbox": bbox,
            "table_caption": caption or []}


def test_cross_page_continuation_keeps_original_header_and_all_rows():
    blocks = content_list_to_blocks([
        _table([["Name", "Latency"], ["A", "1"]], 0, [100, 600, 900, 950]),
        _table([["B", "2"], ["C", "3"]], 1, [100, 50, 900, 300]),
    ])

    assert blocks == [TableBlock(rows=[["Name", "Latency"], ["A", "1"], ["B", "2"], ["C", "3"]], page=1)]


def test_cross_page_continuation_removes_repeated_header():
    blocks = content_list_to_blocks([
        _table([["Name", "Latency"], ["A", "1"]], 0, [100, 600, 900, 950]),
        _table([["Name", "Latency"], ["B", "2"]], 1, [100, 50, 900, 300]),
    ])

    assert blocks == [TableBlock(rows=[["Name", "Latency"], ["A", "1"], ["B", "2"]], page=1)]


def test_continuation_can_span_three_pages_with_single_row_fragments():
    blocks = content_list_to_blocks([
        _table([["Name", "Latency"], ["A", "1"]], 0, [100, 600, 900, 950]),
        _table([["B", "2"]], 1, [100, 50, 900, 950]),
        _table([["C", "3"]], 2, [100, 50, 900, 200]),
    ])

    assert blocks == [TableBlock(rows=[["Name", "Latency"], ["A", "1"], ["B", "2"], ["C", "3"]], page=1)]


@pytest.mark.parametrize("input_format", ["rows", "html"])
def test_cloud_merged_pages_join_only_continuation_before_next_section(input_format):
    items = [
        _table([["Name", "Latency", ""], ["A", "1", ""],
                ["4. Performance", "", ""], ["Name", "QPS", ""],
                ["B", "2", ""]], 0, [100, 100, 900, 950]),
        {"type": "table", "page_idx": 1, "bbox": [100, 50, 900, 950]},
        _table([["C", "3", ""], ["D", "4", ""],
                ["5. Operations", "", ""], ["Name", "Setup", "Backup"],
                ["E", "easy", "daily"]], 2, [100, 50, 900, 700]),
    ]
    if input_format == "html":
        for item in items:
            if "rows" in item:
                item["table_body"] = "<table>" + "".join(
                    "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                    for row in item.pop("rows")
                ) + "</table>"
    blocks = content_list_to_blocks(items)

    tables = [block for block in blocks if isinstance(block, TableBlock)]
    assert len(tables) == 3
    assert tables[1].rows == [["Name", "QPS"], ["B", "2"], ["C", "3"], ["D", "4"]]
    assert tables[1].page == 1
    assert tables[2].rows == [["Name", "Setup", "Backup"], ["E", "easy", "daily"]]


@pytest.mark.parametrize("change", ["caption", "heading", "same_page", "gap", "columns", "position", "alignment", "missing_bbox", "embedded_heading", "different_header"])
def test_separate_tables_are_not_merged(change):
    first = _table([["Name", "Value"], ["A", "1"]], 0, [100, 600, 900, 950])
    second = _table([["B", "2"], ["C", "3"]], 1, [100, 50, 900, 300])
    items = [first, second]
    if change == "caption":
        second["table_caption"] = ["Another table"]
    elif change == "heading":
        items.insert(1, {"type": "text", "text": "New section", "text_level": 1, "page_idx": 1})
    elif change == "same_page":
        second["page_idx"] = 0
    elif change == "gap":
        second["page_idx"] = 2
    elif change == "columns":
        second["rows"] = [["B", "2", "extra"], ["C", "3", "extra"]]
    elif change == "position":
        second["bbox"][1] = 400
    elif change == "alignment":
        second["bbox"][0] = 400
    elif change == "missing_bbox":
        second.pop("bbox")
    elif change == "embedded_heading":
        second["rows"].insert(0, ["2. Another table", ""])
    elif change == "different_header":
        second["rows"].insert(0, ["Name", "Price"])

    tables = [block for block in content_list_to_blocks(items) if isinstance(block, TableBlock)]
    assert len(tables) == 2


def test_unrelated_empty_placeholder_does_not_bridge_tables():
    blocks = content_list_to_blocks([
        _table([["Name", "Value"], ["A", "1"]], 0, [100, 100, 900, 400]),
        {"type": "table", "page_idx": 1, "bbox": [100, 50, 900, 950]},
        _table([["B", "2"], ["C", "3"]], 2, [100, 50, 900, 300]),
    ])

    assert len([block for block in blocks if isinstance(block, TableBlock)]) == 2


pytestmark = pytest.mark.unit


def test_mineru_content_list_merges_text_fragments_and_drops_table_duplicates():
    from kb_api.rag_indexer.parser.common.schema import TableBlock
    from kb_api.rag_indexer.parser.providers.mineru.normalizer import content_list_to_blocks

    blocks = content_list_to_blocks(
        [
            {"type": "text", "text": "稀疏向", "page_idx": 0},
            {"type": "text", "text": "量", "page_idx": 0},
            {"type": "text", "text": "/", "page_idx": 0},
            {
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><td>稀疏向量/关键词搜索</td><td>支持情况</td></tr>"
                    "<tr><td>Milvus</td><td>支持</td></tr>"
                    "</table>"
                ),
                "page_idx": 0,
            },
        ],
    )

    assert blocks == [
        TableBlock(
            rows=[["稀疏向量/关键词搜索", "支持情况"], ["Milvus", "支持"]],
            page=1,
        ),
    ]
def test_mineru_preserves_native_heading_list_and_code():
    from kb_api.rag_indexer.parser.common.schema import TextBlock
    from kb_api.rag_indexer.parser.providers.mineru.normalizer import content_list_to_blocks

    blocks = content_list_to_blocks([
        {"type": "text", "text_level": 1, "text": "Title", "page_idx": 0},
        {"type": "list", "list_items": ["First", "Second"], "page_idx": 0},
        {"type": "code", "code_body": "if x < 1:\n    print(x)\n\n", "page_idx": 0},
    ])
    assert blocks == [TextBlock("Title", page=1, kind="heading", level=1),
                      TextBlock("First", page=1, kind="list_item"),
                      TextBlock("Second", page=1, kind="list_item"),
                      TextBlock("if x < 1:\n    print(x)", page=1, kind="code")]
