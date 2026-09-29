from kb_api.rag_indexer.parser.common.validation import InvalidDocumentError
import threading
import os
import tempfile
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import httpx

from kb_api.rag_indexer.parser.common.validation import validate_pdf_file
from kb_api.rag_indexer.parser.documents.parser import DocumentParser
from kb_api.rag_indexer.parser.common.schema import Block
from kb_api.rag_indexer.parser.providers.mineru.cloud_parser import MineruCloudDocumentParser
from kb_api.rag_indexer.parser.common.config import ParserConfig
from kb_api.rag_indexer.parser.providers.mineru import api_parser


class ParserService:
    OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}

    def __init__(self, config: ParserConfig):
        self.config = config
        self.pdf_parser = self._build_pdf_parser(config)
        self.office_parser = api_parser.MineruApiDocumentParser(replace(config.mineru, enable=True, tier="flash"))
        self.document_parser = DocumentParser()
        self._parse_lock = threading.Lock()
        self.ready = False

    def _build_pdf_parser(self, config: ParserConfig):
        if config.active == "mineru_cloud":
            return MineruCloudDocumentParser(config.mineru_cloud)
        if config.active == "mineru":
            return api_parser.MineruApiDocumentParser(config.mineru)
        raise ValueError(f"Unsupported parser backend: {config.active}")

    def start(self) -> None:
        self.pdf_parser.start()
        self.office_parser.start()
        self.ready = self.pdf_parser.ready and self.office_parser.ready

    def stop(self) -> None:
        self.pdf_parser.stop()
        self.office_parser.stop()
        self.ready = False

    def parse_url(self, presigned_url: str, *, filename: str, http_client: httpx.Client | None = None) -> tuple[list[Block], int | None]:
        ext = Path(filename).suffix.lower()
        if ext not in self.OFFICE_EXTENSIONS and not self.document_parser.supports(filename):
            if ext != ".pdf":
                raise InvalidDocumentError(f"Unsupported file type: {ext}")
            if self.config.active == "mineru_cloud":
                return self.pdf_parser.parse_url(presigned_url), None
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / f"download{Path(filename).suffix}"
            client_context = nullcontext(http_client) if http_client is not None else httpx.Client(follow_redirects=True)
            with client_context as client:
                with client.stream("GET", presigned_url, timeout=self.config.download_timeout) as response:
                    response.raise_for_status()
                    with path.open("wb") as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
            return self.parse_file(str(path), original_filename=filename), path.stat().st_size

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        with self._parse_lock:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.OFFICE_EXTENSIONS:
                return self.office_parser.parse_file(filepath, original_filename=original_filename)
            if self.document_parser.supports(filepath):
                return self.document_parser.parse_file(filepath)
            if ext != ".pdf":
                raise InvalidDocumentError(f"Unsupported file type: {ext}")
            if self.config.active == "mineru_cloud":
                raise InvalidDocumentError("mineru_cloud requires a presigned_url")
            validate_pdf_file(filepath)
            return self.pdf_parser.parse_file(filepath, original_filename=original_filename)
