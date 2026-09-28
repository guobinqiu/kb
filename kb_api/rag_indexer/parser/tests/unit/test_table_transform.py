from kb_api.rag_indexer.parser.common.table_blocks import table_html_to_blocks


def test_logical_tables_remove_only_their_own_empty_columns():
    blocks = table_html_to_blocks(
        '<table><tr><td>Name</td><td>Value</td><td>Unit</td></tr>'
        '<tr><td>A</td><td>1</td><td>ms</td></tr>'
        '<tr><td>2. Next table</td><td></td><td></td></tr>'
        '<tr><td>Name</td><td>Value</td><td></td></tr>'
        '<tr><td>B</td><td>2</td><td></td></tr></table>'
    )

    assert blocks[0].rows == [["Name", "Value", "Unit"], ["A", "1", "ms"]]
    assert blocks[2].rows == [["Name", "Value"], ["B", "2"]]


def test_table_uses_first_single_cell_row_as_title():
    blocks = table_html_to_blocks(
        "<table>"
        "<tr><td>5. 运维复杂度对比</td><td></td><td></td></tr>"
        "<tr><td>向量库</td><td>安装难度</td><td>集群管理</td></tr>"
        "<tr><td>Qdrant</td><td>Docker</td><td>K8s</td></tr>"
        "</table>",
    )

    assert len(blocks) == 1
    assert blocks[0].caption == "5. 运维复杂度对比"
    assert blocks[0].rows == [["向量库", "安装难度", "集群管理"], ["Qdrant", "Docker", "K8s"]]
