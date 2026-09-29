import pytest

from kb_api.rag_indexer.parser.client import LocalParserClient
from kb_api.rag_indexer.parser.common.schema import FormulaBlock, TableBlock, TextBlock
from kb_api.rag_indexer.inference.config_loader import InferenceConfig, SiliconFlowConfig
from kb_api.rag_indexer.inference import service


pytestmark = pytest.mark.unit


def test_local_parser_client_serializes_parser_blocks():
    class Parser:
        ready = True

        def parse_url(self, presigned_url, *, filename):
            assert presigned_url == "https://example.test/file.pdf"
            assert filename == "file.pdf"
            return [
                TextBlock("Title", kind="heading", level=2),
                TableBlock([["a", "b"]], caption="Table"),
                FormulaBlock("x=1"),
            ], 12

    result = LocalParserClient(Parser()).parse_file(
        "https://example.test/file.pdf",
        filename="file.pdf",
    )

    assert result == {
        "blocks": [
            {"type": "text", "text": "Title", "kind": "heading", "level": 2},
            {"type": "table", "rows": [["a", "b"]], "caption": "Table"},
            {"type": "formula", "text": "x=1", "format": "latex"},
        ],
        "file_size": 12,
    }


def test_load_inference_components_uses_selected_provider(monkeypatch):

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["model"] == "dense"

    monkeypatch.setattr(
        "kb_api.rag_indexer.inference.providers.siliconflow.SiliconFlowDenseClient",
        Client,
    )
    config = InferenceConfig(siliconflow=SiliconFlowConfig(
        base_url="https://example.test/v1",
        api_key="secret",
        dense_model="dense",
    ))

    result = service.load_inference_components(config)

    assert isinstance(result.dense, Client)
