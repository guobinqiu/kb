import threading
import time
import pytest

from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.parser.common.config import ParserConfig
import kb_api.rag_indexer.parser.service as service_mod
from kb_api.rag_indexer.parser.common.config import MineruCloudParserConfig
import kb_api.rag_indexer.parser.providers.mineru.api_parser as api_mod


class SlowDocumentParser:
    ready = True

    def __init__(self):
        self.active = 0
        self.max_active = 0

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[dict]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        self.active -= 1
        return [{"id": filepath, "content": original_filename or filepath, "metadata": {}}]


def test_parser_service_serializes_parse_file_calls(monkeypatch):

    monkeypatch.setattr(service_mod, "validate_pdf_file", lambda filepath: None)
    service = ParserService(ParserConfig())
    parser = SlowDocumentParser()
    service.pdf_parser = parser

    threads = [
        threading.Thread(target=service.parse_file, args=(f"file-{index}.pdf",), kwargs={"original_filename": f"file-{index}.pdf"})
        for index in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert parser.max_active == 1


def test_parser_service_uses_mineru_cloud_backend(monkeypatch):

    class FakeMineruCloudDocumentParser:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(service_mod, "MineruCloudDocumentParser", FakeMineruCloudDocumentParser)

    service = ParserService(ParserConfig(active="mineru_cloud", mineru_cloud=MineruCloudParserConfig()))

    assert isinstance(service.pdf_parser, FakeMineruCloudDocumentParser)


def test_parser_service_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unsupported parser backend"):
        ParserService(ParserConfig(active="unknown"))


def test_parser_service_routes_txt_to_local_parser_when_mineru_is_active(tmp_path, monkeypatch):

    class FailingMineruParser:
        ready = True

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def parse_file(self, filepath, *, original_filename=None):
            raise AssertionError("txt should not be parsed by mineru")

    monkeypatch.setattr(api_mod, "MineruApiDocumentParser", FailingMineruParser)
    text_file = tmp_path / "a.txt"
    text_file.write_text("本地文本解析", encoding="utf-8")

    blocks = ParserService(ParserConfig(active="mineru")).parse_file(str(text_file))

    assert blocks[0].text == "本地文本解析"
