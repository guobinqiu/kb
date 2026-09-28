from kb_api.rag_indexer.parser.common.validation import InvalidDocumentError
from kb_api.rag_indexer.parser.common.base import BlockParser
from kb_api.rag_indexer.parser.common.schema import Block, TextBlock
from kb_api.rag_indexer.parser.common.text import clean_cjk_spaces, split_paragraphs


class TxtBlockParser(BlockParser):
    def parse(self, filepath: str) -> list[Block]:
        filename = filepath.rsplit("/", 1)[-1]
        with open(filepath, encoding="utf-8") as file:
            text = clean_cjk_spaces(file.read())
        if not text.strip():
            raise InvalidDocumentError(f"Empty file: {filename}")
        return [TextBlock(paragraph, kind="paragraph") for paragraph in split_paragraphs(text)]
