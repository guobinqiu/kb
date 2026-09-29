import pytest
from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.parser.common.config import ParserConfig
from kb_api.rag_indexer.parser.common.schema import TextBlock
from kb_api.rag_indexer.parser.common.schema import TableBlock
import json
from kb_api.rag_indexer.parser.common.schema import FormulaBlock
from kb_api.rag_indexer.parser.providers.mineru.normalizer import read_content_list_blocks


pytestmark = pytest.mark.integration


def _parse_file(filepath: str, original_filename: str | None = None, parser=None):

    parser_service = ParserService(parser or ParserConfig())
    return parser_service.parse_file(filepath, original_filename=original_filename)


def test_parse_txt_file_returns_text_blocks(test_txt_path):

    blocks = _parse_file(test_txt_path)

    assert blocks
    assert all(isinstance(block, TextBlock) for block in blocks)
    assert "人工智能" in "\n".join(block.text for block in blocks)


def test_parse_md_file_returns_text_and_table_blocks(tmp_path):

    md_file = tmp_path / "table.md"
    md_file.write_text(
        "# 数据库对比\n\n"
        "| 向量库 | 能力 |\n"
        "| --- | --- |\n"
        "| Qdrant | 过滤 |\n"
        "| Milvus | 分布式 |\n",
        encoding="utf-8",
    )

    blocks = _parse_file(str(md_file))

    assert isinstance(blocks[0], TextBlock)
    assert blocks[0].text == "# 数据库对比"
    assert any(isinstance(block, TableBlock) and ["Qdrant", "过滤"] in block.rows for block in blocks)


def test_parse_invalid_files_raise_clear_errors(tmp_path):
    invalid_files = [
        ("fake.pdf", "Invalid pdf file"),
    ]

    for filename, message in invalid_files:
        path = tmp_path / filename
        path.write_text("invalid", encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            _parse_file(str(path))


def test_mineru_content_list_returns_clean_blocks(tmp_path):

    output_dir = tmp_path / "mineru-output"
    output_dir.mkdir()
    (output_dir / "demo_content_list.json").write_text(
        json.dumps([
            {"type": "text", "text": "稀疏向", "page_idx": 0},
            {"type": "text", "text": "量", "page_idx": 0},
            {
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><td>稀疏向量</td><td>支持情况</td></tr>"
                    "<tr><td>Milvus</td><td>支持</td></tr>"
                    "</table>"
                ),
                "page_idx": 0,
            },
            {"type": "image", "img_path": "images/a.jpg", "img_caption": ["图片说明"]},
            {"type": "chart", "img_path": "images/chart.jpg", "content": "图表内容"},
            {"type": "equation", "text": "E=mc^2", "text_format": "latex", "page_idx": 0},
        ]),
        encoding="utf-8",
    )

    blocks = read_content_list_blocks(output_dir)

    assert blocks == [
        TableBlock(
            rows=[["稀疏向量", "支持情况"], ["Milvus", "支持"]],
            page=1,
        ),
        FormulaBlock("E=mc^2", page=1),
    ]
