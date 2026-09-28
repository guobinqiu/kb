from pathlib import Path

from kb_api.rag_indexer.parser.documents.md import MdBlockParser
from kb_api.rag_indexer.parser.documents.txt import TxtBlockParser


class DocumentParser:
    def __init__(self):
        self.parsers = {
            ".txt": TxtBlockParser(),
            ".md": MdBlockParser(),
        }

    def supports(self, filename: str) -> bool:
        suffix = Path(filename).suffix.lower()
        return suffix in self.parsers

    def parse_file(self, filepath: str, *, original_filename: str | None = None):
        suffix = Path(original_filename or filepath).suffix.lower()
        return self.parsers[suffix].parse(filepath)
