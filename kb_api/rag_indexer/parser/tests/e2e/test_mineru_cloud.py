import os

import pytest

from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.parser.common.config import MineruCloudParserConfig, ParserConfig


pytestmark = pytest.mark.e2e


def test_mineru_cloud_public_pdf():
    token = os.environ.get("MINERU_API_KEY")
    if not token:
        pytest.skip("MINERU_API_KEY is required")
    service = ParserService(ParserConfig(
        active="mineru_cloud",
        mineru_cloud=MineruCloudParserConfig(api_key=token),
    ))
    try:
        service.start()
        blocks, size = service.parse_url(
            "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
            filename="example.pdf",
        )
        assert blocks
        assert any(getattr(block, "text", None) or getattr(block, "rows", None) for block in blocks)
    finally:
        service.stop()
