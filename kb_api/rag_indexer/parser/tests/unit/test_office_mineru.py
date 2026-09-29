import json
from pathlib import Path

import httpx
import pytest

from kb_api.rag_indexer.parser.common.config import MineruApiServerConfig, MineruCloudParserConfig, ParserConfig
from kb_api.rag_indexer.parser.providers.mineru.api_parser import MineruApiDocumentParser
from kb_api.rag_indexer.parser.service import ParserService
import kb_api.rag_indexer.parser.providers.mineru.api_parser as api_mod


@pytest.mark.parametrize("suffix", [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"])
@pytest.mark.parametrize("active", ["mineru", "mineru_cloud"])
def test_office_routes_to_mineru_flash(tmp_path, monkeypatch, suffix, active):

    class OfficeParser:
        ready = False

        def __init__(self, config):
            self.config = config

        def start(self):
            self.ready = True

        def stop(self):
            self.ready = False

        def parse_file(self, filepath, original_filename=None):
            return [self.config.tier, original_filename, Path(filepath).read_bytes()]

    monkeypatch.setattr(api_mod, "MineruApiDocumentParser", OfficeParser)
    service = ParserService(ParserConfig(active=active, mineru=MineruApiServerConfig(tier="standard"),
                                         mineru_cloud=MineruCloudParserConfig(api_key="test-token")))
    source = tmp_path / f"input{suffix}"
    source.write_bytes(b"office")
    service.start()
    try:
        assert service.parse_file(str(source), original_filename=f"report{suffix}") == ["flash", f"report{suffix}", b"office"]
    finally:
        service.stop()
    assert not service.office_parser.ready


def test_office_url_download_is_cleaned_after_flash_parse(monkeypatch):
    service = ParserService(ParserConfig())
    paths = []

    def parse(filepath, original_filename=None):
        paths.append(Path(filepath))
        return [Path(filepath).read_bytes(), original_filename]

    monkeypatch.setattr(service.office_parser, "parse_file", parse)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"office"))) as client:
        assert service.parse_url("https://storage.example/report", filename="report.xls", http_client=client) == ([b"office", "report.xls"], 6)
    assert not paths[0].exists()


@pytest.mark.parametrize("filename,mime", [
    ("a.doc", "application/msword"),
    ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("a.xls", "application/vnd.ms-excel"),
    ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("a.ppt", "application/vnd.ms-powerpoint"),
    ("a.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
])
def test_office_api_uploads_correct_mime_and_requests_flash(tmp_path, filename, mime):
    source = tmp_path / filename
    source.write_bytes(b"office")
    uploads = []
    jobs = []

    def handle(request):
        path = request.url.path
        if path == "/v1/uploads":
            uploads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "upload-1", "upload_url": "/upload", "upload_headers": {}})
        if path == "/upload":
            return httpx.Response(200)
        if path.endswith("/complete"):
            return httpx.Response(200, json={"file": {"id": "input-1"}})
        if path == "/v1/parse/jobs":
            jobs.append(json.loads(request.content))
            return httpx.Response(200, json={"job_id": "job-1", "status": "completed", "files": [{
                "status": "completed", "output_files": {"structured_content": {"file_id": "output-1"}},
            }]})
        return httpx.Response(200, json={"pages": [{"page_idx": 0, "blocks": [{"type": "text", "content": "Office result"}]}]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        parser = MineruApiDocumentParser(MineruApiServerConfig(tier="flash"), http_client=client)
        blocks = parser.parse_file(str(source), original_filename=filename)

    assert uploads[0]["filename"] == filename
    assert uploads[0]["mime_type"] == mime
    assert jobs[0]["tier"] == "flash"
    assert blocks[0].text == "Office result"
