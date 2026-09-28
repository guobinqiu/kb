from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.parser.common.config import ParserConfig


def test_parser_downloads_url_once_and_cleans_file(monkeypatch):
    service = ParserService(ParserConfig())
    paths = []

    def parse_file(path, *, original_filename):
        paths.append(Path(path))
        assert Path(path).read_bytes() == b"hello"
        assert original_filename == "report.txt"
        return ["block"]

    def download(request):
        assert str(request.url) == "https://source.example/report?signature=abc"
        return httpx.Response(200, content=b"hello")

    monkeypatch.setattr(service, "parse_file", parse_file)
    with httpx.Client(transport=httpx.MockTransport(download)) as client:
        result = service.parse_url("https://source.example/report?signature=abc", filename="report.txt", http_client=client)
    assert result == (["block"], 5)
    assert len(paths) == 1
    assert not paths[0].exists()


def test_parser_cleans_download_when_parsing_fails(monkeypatch):
    service = ParserService(ParserConfig())
    paths = []

    def fail(path, **kwargs):
        paths.append(Path(path))
        raise ValueError("bad document")

    monkeypatch.setattr(service, "parse_file", fail)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad"))) as client:
        with pytest.raises(ValueError, match="bad document"):
            service.parse_url("https://source.example/a.pdf", filename="a.pdf", http_client=client)
    assert not paths[0].exists()


@pytest.mark.parametrize("filename", ["a.pdf"])
def test_cloud_routes_url_without_local_download(filename):
    service = ParserService(ParserConfig(active="mineru_cloud"))
    calls = []
    service.pdf_parser = SimpleNamespace(parse_url=lambda url: calls.append(url) or ["cloud block"])

    def forbidden(request):
        raise AssertionError("Parser must not download cloud input")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert service.parse_url("https://source/file", filename=filename, http_client=client) == (["cloud block"], None)
    assert calls == ["https://source/file"]


def test_url_download_uses_configured_timeout():
    service = ParserService(ParserConfig(download_timeout=33))

    def handle(request):
        assert request.extensions["timeout"]["read"] == 33
        return httpx.Response(200, content=b"hello")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        blocks, size = service.parse_url("https://source/a.txt", filename="a.txt", http_client=client)
    assert blocks[0].text == "hello"
    assert size == 5


def test_cloud_config_reads_token_from_environment(tmp_path, monkeypatch):
    from kb_api.rag_indexer.parser.config_loader import load_parser_config

    monkeypatch.setenv("MINERU_API_KEY", "cloud-token")
    config_file = tmp_path / "parser.yaml"
    config_file.write_text("parser:\n  download_timeout: 45\n  mineru_cloud:\n    enable: true\n    model_version: vlm\n")
    config = load_parser_config(config_file)
    assert config.active == "mineru_cloud"
    assert config.download_timeout == 45
    assert config.mineru_cloud.api_key == "cloud-token"
    assert config.mineru_cloud.model_version == "vlm"
