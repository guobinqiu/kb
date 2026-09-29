import pytest
from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.parser.common.config import ParserConfig
from kb_api.rag_indexer.parser.documents.md import MdBlockParser
from kb_api.rag_indexer.parser.documents.txt import TxtBlockParser
import kb_api.rag_indexer.parser.providers.mineru.api_parser as api_mod
from PIL import Image
from kb_api.rag_indexer.parser.common.schema import TextBlock
from kb_api.rag_indexer.parser.common.config import MineruApiServerConfig


pytestmark = pytest.mark.unit


def _create_minimal_pdf(path: str, text: str):
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content_stream = f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET".encode("latin-1")
    content_len = len(content_stream)

    objs: list[bytes] = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R"
        b"/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n",
        (
            f"4 0 obj<</Length {content_len}>>stream\n".encode("latin-1")
            + content_stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
    ]

    header = b"%PDF-1.4\n"
    pos = len(header)
    offsets = [0] * 6
    for i, blob in enumerate(objs, start=1):
        offsets[i] = pos
        pos += len(blob)

    xref_start = pos
    xref_lines = [f"xref\n0 6\n{offsets[0]:010d} 65535 f \n"]
    xref_lines += [f"{o:010d} 00000 n \n" for o in offsets[1:]]
    xref = "".join(xref_lines)
    trailer = f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF"

    with open(path, "wb") as f:
        f.write(header)
        for blob in objs:
            f.write(blob)
        f.write(xref.encode("ascii"))
        f.write(trailer.encode("ascii"))


def _parse_file(filepath: str, original_filename: str | None = None, parser=None):

    parser_service = ParserService(parser or ParserConfig())
    return parser_service.parse_file(filepath, original_filename=original_filename)


def test_document_parsers_use_suffix_module_names():

    assert MdBlockParser
    assert TxtBlockParser


def test_parse_md_embedded_image_does_not_invoke_document_backend(tmp_path, monkeypatch):

    class FailingMineruParser:
        ready = True

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def parse_file(self, filepath, *, original_filename=None):
            raise AssertionError("markdown should not be parsed by document backend")

    monkeypatch.setattr(api_mod, "MineruApiDocumentParser", FailingMineruParser)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    outside_image = tmp_path / "outside.png"
    Image.new("RGB", (10, 10), "white").save(str(outside_image))
    md_file = docs_dir / "image.md"
    md_file.write_text("# 图片说明\n\n![note](../outside.png)\n", encoding="utf-8")

    blocks = _parse_file(str(md_file))

    assert "图片说明" in "\n".join(block.text for block in blocks)


def test_parse_pdf_routes_to_active_document_backend(tmp_path):

    pdf_file = tmp_path / "test.pdf"
    _create_minimal_pdf(str(pdf_file), "PDF test")
    service = ParserService(ParserConfig(active="mineru"))
    calls = []

    class FakeDocumentParser:
        ready = True

        def parse_file(self, filepath, *, original_filename=None):
            calls.append((filepath, original_filename))
            return [TextBlock("PDF test")]

    service.pdf_parser = FakeDocumentParser()

    blocks = service.parse_file(str(pdf_file), original_filename="upload.pdf")

    assert calls == [(str(pdf_file), "upload.pdf")]
    assert blocks == [TextBlock("PDF test")]


@pytest.mark.parametrize("tier", ["flash", "basic", "standard", "advanced"])
def test_pdf_parser_preserves_configured_tier(tier):

    service = ParserService(ParserConfig(mineru=MineruApiServerConfig(tier=tier)))

    assert service.pdf_parser.config.tier == tier


def test_parse_unsupported_file_type_raises_before_document_backend(tmp_path, monkeypatch):

    class FailingMineruParser:
        ready = True

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def parse_file(self, filepath, *, original_filename=None):
            raise AssertionError("unsupported files should not reach document backend")

    monkeypatch.setattr(api_mod, "MineruApiDocumentParser", FailingMineruParser)
    path = tmp_path / "data.png"
    path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file type"):
        _parse_file(str(path))
