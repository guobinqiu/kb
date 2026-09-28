import pytest

from kb_api.rag_indexer.core.index.chunking import parser_blocks_to_chunks
from kb_api.rag_indexer.common.config import ChunkingConfig, TextParserConfig


def test_table_absorbs_preceding_text_and_following_text_stays_separate():
    config = ChunkingConfig(text=TextParserConfig(chunk_size=200, chunk_overlap=20))
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "前置说明文字很长"},
            {"type": "table", "rows": [["库", "能力"], ["Qdrant", "过滤"]]},
            {"type": "text", "text": "后置说明文字很长"},
        ],
        "report.pdf",
        config,
    )

    # 表格吸收前一个相邻文本 chunk 作为前缀（原文保留一份）；后置文本独立成块
    assert [chunk["content"] for chunk in chunks] == [
        "前置说明文字很长",
        "前置说明文字很长\n| 库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |",
        "后置说明文字很长",
    ]


def test_table_chunks_include_filename_metadata():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "表格标题"},
            {"type": "table", "rows": [["库", "能力"], ["Qdrant", "过滤"]]},
        ],
        "report.pdf",
        ChunkingConfig(),
    )

    table_chunks = [chunk for chunk in chunks if "| Qdrant | 过滤 |" in chunk["content"]]
    assert len(table_chunks) == 1
    assert table_chunks[0]["metadata"]["filename"] == "report.pdf"


def test_tables_do_not_infer_headings_from_unclassified_text():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "1. 数据规模对比"},
            {"type": "table", "rows": [["向量库", "能力"], ["Qdrant", "过滤"]]},
            {"type": "text", "text": "2. 查询类型对比"},
            {"type": "table", "rows": [["向量库", "查询"], ["Milvus", "混合检索"]]},
        ],
        "report.pdf",
        ChunkingConfig(),
    )
    table_chunks = [chunk for chunk in chunks if "| Qdrant | 过滤 |" in chunk["content"] or "| Milvus | 混合检索 |" in chunk["content"]]

    # 未识别为 heading 的碎文本不进 caption；主循环把前一个相邻文本 chunk 复制为表格前缀
    assert len(table_chunks) == 2
    assert table_chunks[0]["content"] == "1. 数据规模对比\n| 向量库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |"
    assert table_chunks[1]["content"] == "2. 查询类型对比\n| 向量库 | 查询 |\n| --- | --- |\n| Milvus | 混合检索 |"


@pytest.mark.parametrize("filename", ["report.pdf", "report.docx", "report.doc", "report.md", "report.pptx"])
def test_heading_and_complete_table_share_one_chunk(filename):
    rows = [["Name", "Value"]] + [[f"row-{index}", "value"] for index in range(30)]
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "paragraph", "text": "Introduction"},
        {"type": "text", "kind": "heading", "text": "Table title"},
        {"type": "table", "rows": rows},
        {"type": "text", "kind": "paragraph", "text": "After"},
    ], filename, ChunkingConfig(text=TextParserConfig(chunk_size=700, chunk_overlap=0)))
    # heading 挂靠进 caption；表格吸收前一个文本 chunk（Introduction）为前缀；
    # Introduction 原文与 After 独立成块（文本之间不再合并）
    assert chunks[0]["content"] == "Introduction"
    table_content = chunks[1]["content"]
    assert table_content.startswith("Introduction\nTable title\n| Name | Value |\n| --- | --- |\n")
    assert table_content.endswith("| row-29 | value |")
    assert chunks[2]["content"] == "After"
    assert [chunk["metadata"]["chunk_index"] for chunk in chunks] == [0, 1, 2]


@pytest.mark.parametrize("heading", ["Table title", "## Table title", "Table title\n==========="])
def test_table_caption_does_not_repeat_adjacent_heading(heading):
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "heading", "text": heading},
        {"type": "table", "caption": "Table title", "rows": [["Name"], ["A"]]},
    ], "report.md", ChunkingConfig())
    assert len(chunks) == 1
    assert chunks[0]["content"] == heading + "\n| Name |\n| --- |\n| A |"


@pytest.mark.parametrize("caption", ["8. 核心区别对比", "核心区别对比"])
def test_recap_caption_merged_with_heading_single_copy(caption):
    # caption 与 heading 完全相同，或为 heading 去前缀的复述 → 只保留 heading 一份
    blocks = [
        {"type": "text", "kind": "heading", "text": "8. 核心区别对比", "page": 5},
        {"type": "table", "caption": caption, "page": 5,
         "rows": [["向量库", "能力"], ["Qdrant", "过滤"]]},
    ]
    chunks = parser_blocks_to_chunks(blocks, "报告.pdf", ChunkingConfig())
    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert content.startswith("8. 核心区别对比")
    assert content.count("核心区别对比") == 1


def test_distinct_caption_kept_with_heading():
    # caption 含独立信息（表N/年份）→ heading 与 caption 都保留，各出现一次
    blocks = [
        {"type": "text", "kind": "heading", "text": "3. 部署架构", "page": 5},
        {"type": "table", "caption": "表5：2024年各云厂商部署统计", "page": 5,
         "rows": [["云厂商", "部署量"], ["厂商A", "100"]]},
    ]
    chunks = parser_blocks_to_chunks(blocks, "报告.pdf", ChunkingConfig())
    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert content.count("3. 部署架构") == 1
    assert content.count("表5：2024年各云厂商部署统计") == 1


def test_bare_table_keeps_own_caption():
    # 裸表（无挂靠标题）→ 直接使用 block 自带的 caption
    chunks = parser_blocks_to_chunks(
        [{"type": "table", "caption": "表5：统计", "rows": [["名称", "值"], ["甲", "1"]]}],
        "report.pdf",
        ChunkingConfig(),
    )
    assert len(chunks) == 1
    assert "表5：统计" in chunks[0]["content"]


def test_consecutive_headings_attach_and_distinct_caption_kept():
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "heading", "text": "Parent"},
        {"type": "text", "kind": "heading", "text": "Child"},
        {"type": "table", "caption": "Table 1", "rows": [["Name"], ["A"]]},
    ], "report.docx", ChunkingConfig())
    contents = [chunk["content"] for chunk in chunks]
    assert contents == ["Parent\n\nChild\nTable 1\n| Name |\n| --- |\n| A |"]
    assert contents[0].count("Table 1") == 1


def test_heading_with_body_is_not_moved_into_table():
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "heading", "text": "Title"},
        {"type": "text", "kind": "paragraph", "text": "Body"},
        {"type": "table", "rows": [["Name"], ["A"]]},
    ], "report.docx", ChunkingConfig())
    # 主循环不把带正文的标题挪进表格 caption；表格吸收前一个文本 chunk（Title\n\nBody）为前缀
    assert [chunk["content"] for chunk in chunks] == [
        "Title\n\nBody",
        "Title\n\nBody\n| Name |\n| --- |\n| A |",
    ]


def test_page_trailing_heading_on_slide_attaches_to_next_page_table():
    # 纯标题 pending 允许跨页挂靠下页表格，避免页尾标题被切成孤块
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "heading", "text": "Title", "page": 1},
        {"type": "table", "rows": [["Name"], ["A"]], "page": 2},
    ], "report.pptx", ChunkingConfig())
    assert [chunk["content"] for chunk in chunks] == ["Title\n| Name |\n| --- |\n| A |"]
    assert chunks[0]["metadata"]["page"] == 2


def test_table_keeps_all_rows_beyond_chunk_limit_and_keeps_own_caption():
    rows = [["名称", "大小"]] + [[f"file-{index}", "70MB"] for index in range(30)]
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "前文"},
            {"type": "table", "caption": "文件大小", "rows": rows},
            {"type": "text", "text": "后文"},
        ],
        "report.md",
        ChunkingConfig(text=TextParserConfig(chunk_size=20, chunk_overlap=0)),
    )

    # 表格无条件整块输出为单个 chunk（chunk_size 不触发切分），所有行保留；
    # 表格吸收"前文"为前缀；"后文"独立成块；block caption 保留且不重复
    assert len(chunks) == 3
    content = chunks[1]["content"]
    assert content.startswith("前文\n文件大小\n| 名称 | 大小 |\n| --- | --- |\n")
    for index in range(30):
        assert f"| file-{index} | 70MB |" in content
    assert content.endswith("| file-29 | 70MB |")
    assert content.count("文件大小") == 1
    assert chunks[2]["content"] == "后文"


def test_combines_consecutive_parser_text_blocks():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "第一段说明合同履行背景。"},
            {"type": "text", "text": "PDF 抽取出来的第一行"},
            {"type": "text", "text": "PDF 抽取出来的第二行"},
            {"type": "text", "text": "第二段说明代理制度背景。"},
        ],
        "report.pdf",
        ChunkingConfig(),
    )

    assert [chunk["content"] for chunk in chunks] == ["\n\n".join([
        "第一段说明合同履行背景。",
        "PDF 抽取出来的第一行",
        "PDF 抽取出来的第二行",
        "第二段说明代理制度背景。",
    ])]


def test_splits_blank_line_paragraphs_inside_text_block():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "第一段\n段内换行\n\n第二段\r\n \r\n第三段"},
        ],
        "report.txt",
        ChunkingConfig(),
    )

    assert [chunk["content"] for chunk in chunks] == [
        "第一段\n段内换行", "第二段", "第三段",
    ]


def test_text_chunks_keep_complete_paragraphs_when_they_fit():
    paragraphs = ["第一段介绍检索。", "第二段介绍索引。", "第三段介绍解析。"]
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": text} for text in paragraphs],
        "notes.txt",
        ChunkingConfig(text=TextParserConfig(chunk_size=20, chunk_overlap=0)),
    )

    assert [chunk["content"] for chunk in chunks] == paragraphs


def test_markdown_code_block_keeps_internal_blank_lines():
    code = "```python\nx = 1\n\nprint(x)\n```"
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": "说明"}, {"type": "text", "kind": "code", "text": code}],
        "sample.md", ChunkingConfig(),
    )
    assert [chunk["content"] for chunk in chunks] == ["说明\n\n" + code]


def test_small_adjacent_section_chunks_stay_separate_in_order():
    blocks = [
        {"type": "text", "kind": kind, "text": text}
        for kind, text in [("heading", "Architecture"), ("paragraph", "Three parts:"),
                           ("list_item", "- Router"), ("list_item", "- Runtime"),
                           ("heading", "Deployment"), ("text", "Run the service")]
    ]
    chunks = parser_blocks_to_chunks(blocks, "report.docx", ChunkingConfig())
    # 主循环在 heading 处切分；两个 section 均独立成块（文本之间不做合并），顺序保留
    assert [chunk["content"] for chunk in chunks] == [
        "Architecture\n\nThree parts:\n- Router\n- Runtime",
        "Deployment\n\nRun the service",
    ]


def test_consecutive_headings_followed_by_body_stay_together():
    blocks = [{"type": "text", "kind": kind, "text": text}
              for kind, text in [("heading", "Parent"), ("heading", "Child"), ("paragraph", "Body")]]
    chunks = parser_blocks_to_chunks(blocks, "report.md", ChunkingConfig())
    assert [chunk["content"] for chunk in chunks] == ["Parent\n\nChild\n\nBody"]


def test_code_chunk_preserves_leading_indentation_and_exceeds_text_limit():
    code = "    print(x)\n\n    print(y)"
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "kind": "code", "text": code}], "report.pdf",
        ChunkingConfig(text=TextParserConfig(chunk_size=10, chunk_overlap=0)),
    )
    assert [chunk["content"] for chunk in chunks] == [code]


def test_heading_is_not_orphaned_when_following_paragraph_exceeds_limit():
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "kind": "heading", "text": "Title"},
         {"type": "text", "kind": "paragraph", "text": "a" * 50}],
        "report.docx", ChunkingConfig(text=TextParserConfig(chunk_size=20, chunk_overlap=0)),
    )
    # 主循环把标题与正文首个切分片合块（标题不孤立）；后续切分片独立成块，内容无丢失
    assert chunks[0]["content"] == "Title\n\n" + "a" * 13
    assert sum(chunk["content"].count("a") for chunk in chunks) == 50


def test_nested_list_indentation_is_preserved():
    blocks = [{"type": "text", "kind": "list_item", "text": text} for text in ["- Parent", "  - Child"]]
    chunks = parser_blocks_to_chunks(blocks, "report.md", ChunkingConfig())
    assert [chunk["content"] for chunk in chunks] == ["- Parent\n  - Child"]


def test_pptx_slide_chunks_split_at_page_boundaries():
    blocks = [{"type": "text", "kind": "paragraph", "text": "abcdef", "page": page}
              for page in [1, 1, 2]]
    chunks = parser_blocks_to_chunks(blocks, "slides.pptx", ChunkingConfig())
    # 主循环按页边界切分；同页短文本并入 pending，跨页独立成块（无合并 pass）
    assert [chunk["content"] for chunk in chunks] == ["abcdef\n\nabcdef", "abcdef"]
    chunks = parser_blocks_to_chunks(blocks, "slides.pptx", ChunkingConfig(text=TextParserConfig(chunk_size=10, chunk_overlap=0)))
    assert [chunk["content"] for chunk in chunks] == ["abcdef", "abcdef", "abcdef"]


def test_pptx_table_absorbs_previous_page_text():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "上一页", "page": 1},
            {"type": "table", "rows": [["名称", "值"], ["甲", "1"]], "page": 2},
            {"type": "text", "text": "下一页", "page": 3},
        ],
        "slides.pptx", ChunkingConfig(),
    )
    # 主循环保证表格不带上一页文本作 caption；表格吸收前一个相邻文本 chunk 为前缀；
    # 后续文本独立成块
    assert [chunk["content"] for chunk in chunks] == [
        "上一页",
        "上一页\n| 名称 | 值 |\n| --- | --- |\n| 甲 | 1 |",
        "下一页",
    ]


def test_long_paragraph_splits_at_sentences_and_keeps_punctuation():
    sentences = ["这是第一句话。", "这是第二句话！", "这是第三句话？"]
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": "".join(sentences)}],
        "notes.txt",
        ChunkingConfig(text=TextParserConfig(chunk_size=10, chunk_overlap=0)),
    )

    assert [chunk["content"] for chunk in chunks] == sentences


def test_text_without_boundaries_uses_character_limit_and_overlap():
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": "abcdefghijklmnopqrstuvwxyz"}],
        "notes.txt",
        ChunkingConfig(text=TextParserConfig(chunk_size=10, chunk_overlap=2)),
    )

    assert [chunk["content"] for chunk in chunks] == ["abcdefghij", "ijklmnopqr", "qrstuvwxyz"]


def test_normalized_chinese_sentence_punctuation_keeps_boundaries():
    sentences = ["这是第一句话!", "这是第二句话?", "这是第三句话。"]
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": "".join(sentences)}],
        "notes.txt",
        ChunkingConfig(text=TextParserConfig(chunk_size=10, chunk_overlap=0)),
    )

    assert [chunk["content"] for chunk in chunks] == sentences


def test_page_trailing_heading_attaches_to_next_page_table():
    chunks = parser_blocks_to_chunks([
        {"type": "text", "kind": "heading", "text": "2. 查询类型对比", "page": 3},
        {"type": "table", "rows": [["向量库", "查询"], ["Milvus", "混合检索"]], "page": 4},
    ], "report.pdf", ChunkingConfig())

    assert len(chunks) == 1
    assert chunks[0]["content"] == "2. 查询类型对比\n| 向量库 | 查询 |\n| --- | --- |\n| Milvus | 混合检索 |"
    assert chunks[0]["metadata"]["page"] == 4


def test_table_absorbs_previous_adjacent_text_chunk():
    # 文本块 A（短标题，kind=text 未识别为 heading）+ 表格 → A 独立保留 + 表格以 A 为前缀
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "kind": "text", "text": "7. 架构类型对比"},
            {"type": "table", "rows": [["向量库", "能力"], ["Qdrant", "过滤"]]},
        ],
        "report.pdf",
        ChunkingConfig(),
    )

    assert len(chunks) == 2
    assert chunks[0]["content"] == "7. 架构类型对比"  # 原文本 chunk 保留不动
    assert chunks[1]["content"] == "7. 架构类型对比\n| 向量库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |"
    assert chunks[1]["metadata"]["block_type"] == "table"


def test_table_absorbs_long_previous_text_full_copy():
    # 前面是接近 chunk_size 的长正文 + 表格 → 表格 chunk 含完整正文副本（吸收不限长度）
    body = "正" * 95
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": body},
            {"type": "table", "rows": [["库", "能力"], ["Qdrant", "过滤"]]},
        ],
        "report.pdf",
        ChunkingConfig(text=TextParserConfig(chunk_size=100, chunk_overlap=0)),
    )

    assert len(chunks) == 2
    assert chunks[0]["content"] == body
    assert chunks[1]["content"] == body + "\n| 库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |"
    assert chunks[1]["metadata"]["block_type"] == "table"


def test_consecutive_tables_do_not_absorb_each_other():
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "text": "对比说明"},
            {"type": "table", "rows": [["库", "能力"], ["Qdrant", "过滤"]]},
            {"type": "table", "rows": [["库", "查询"], ["Milvus", "混合检索"]]},
        ],
        "report.pdf",
        ChunkingConfig(),
    )

    # 表A 吸收前一个文本 chunk；表B 不吸收表A（block_type 标记判断），content 就是自己的表格文本
    assert len(chunks) == 3
    assert chunks[1]["content"] == "对比说明\n| 库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |"
    assert chunks[2]["content"] == "| 库 | 查询 |\n| --- | --- |\n| Milvus | 混合检索 |"
    assert chunks[1]["metadata"]["block_type"] == "table"
    assert chunks[2]["metadata"]["block_type"] == "table"


def test_bare_table_without_previous_chunk():
    # 表格是第一个块 → 无前缀，正常独立
    chunks = parser_blocks_to_chunks(
        [{"type": "table", "rows": [["名称", "值"], ["甲", "1"]]}],
        "report.pdf",
        ChunkingConfig(),
    )

    assert len(chunks) == 1
    assert chunks[0]["content"] == "| 名称 | 值 |\n| --- | --- |\n| 甲 | 1 |"
    assert chunks[0]["metadata"]["block_type"] == "table"


def test_txt_small_chunks_not_merged():
    text = "问：服务地址是什么？\n\n答：127.0.0.1:8080\n\n问：超时时间是多少？\n\n答：默认 30 秒"
    chunks = parser_blocks_to_chunks(
        [{"type": "text", "text": text}],
        "报告.txt",
        ChunkingConfig(),
    )

    # txt 按空行分段，短段（如 QA 对）是独立检索单元；已无任何合并逻辑，天然保持原粒度
    assert [chunk["content"] for chunk in chunks] == [
        "问：服务地址是什么？",
        "答：127.0.0.1:8080",
        "问：超时时间是多少？",
        "答：默认 30 秒",
    ]


def test_mineru_style_orphan_heading_and_table():
    # 实测场景复现：MinerU 输出的 kind=text 孤标题与同页表格
    # → 标题独立成 chunk + 表格 chunk 以标题为前缀（两路可检索）
    blocks = [
        {"type": "text", "kind": "text", "text": "7. 架构类型对比", "page": 4},
        {"type": "table", "caption": "", "page": 4, "rows": [
            ["向量库", "架构"],
            ["Milvus", "云原生分布式架构设计"],
            ["Qdrant", "Rust 实现的轻量级向量检索引擎"],
            ["Weaviate", "内置向量的图数据搜索引擎"],
        ]},
    ]
    chunks = parser_blocks_to_chunks(blocks, "报告.pdf", ChunkingConfig())

    assert len(chunks) == 2
    assert chunks[0]["content"] == "7. 架构类型对比"
    assert chunks[0]["metadata"]["page"] == 4
    assert chunks[1]["content"] == (
        "7. 架构类型对比\n"
        "| 向量库 | 架构 |\n| --- | --- |\n"
        "| Milvus | 云原生分布式架构设计 |"
        "\n| Qdrant | Rust 实现的轻量级向量检索引擎 |"
        "\n| Weaviate | 内置向量的图数据搜索引擎 |"
    )
    assert chunks[1]["metadata"]["block_type"] == "table"
    assert chunks[1]["metadata"]["page"] == 4


def test_oversized_table_kept_as_single_chunk():
    rows = [["向量库", "能力"]] + [[f"engine-{index}", "filter"] for index in range(30)]
    chunks = parser_blocks_to_chunks(
        [
            {"type": "text", "kind": "heading", "text": "能力对比", "page": 2},
            {"type": "table", "caption": "能力对比", "rows": rows, "page": 2},
        ],
        "report.pdf",
        ChunkingConfig(),
    )

    # 表格无条件整块输出为单个 chunk（不做行组切分），heading 前缀和表头保留，
    # 复述型 caption（heading 子串）与 heading 合并为一份
    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert content.startswith("能力对比\n| 向量库 | 能力 |\n| --- | --- |\n")
    assert content.count("能力对比") == 1
    assert chunks[0]["metadata"]["page"] == 2
    body_lines = [line for line in content.splitlines() if line.startswith("| engine-")]
    assert body_lines == [f"| engine-{index} | filter |" for index in range(30)]
