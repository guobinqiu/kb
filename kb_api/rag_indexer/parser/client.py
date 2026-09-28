from __future__ import annotations

from kb_api.rag_indexer.common.contracts import (
    ParseFileResponse,
    ParserFormulaBlock,
    ParserTableBlock,
    ParserTextBlock,
)
from kb_api.rag_indexer.parser.common.schema import FormulaBlock, TableBlock, TextBlock
from kb_api.rag_indexer.parser.service import ParserService


class LocalParserClient:
    def __init__(self, service: ParserService):
        self.service = service

    @property
    def ready(self) -> bool:
        return self.service.ready

    def start(self) -> None:
        self.service.start()

    def close(self) -> None:
        self.service.stop()

    def stop(self) -> None:
        self.close()

    def ping(self) -> bool:
        return self.ready

    def parse_file(self, presigned_url: str, *, filename: str) -> dict:
        blocks, file_size = self.service.parse_url(presigned_url, filename=filename)
        response = ParseFileResponse(
            blocks=[_serialize_block(block) for block in blocks],
            file_size=file_size,
        )
        return response.model_dump(exclude_none=True)


def _serialize_block(block):
    if isinstance(block, TextBlock):
        return ParserTextBlock(
            text=block.text,
            page=block.page,
            kind=block.kind,
            level=block.level if block.kind == "heading" else None,
        )
    if isinstance(block, TableBlock):
        return ParserTableBlock(
            rows=block.rows,
            caption=block.caption.strip() or None,
            page=block.page,
        )
    if isinstance(block, FormulaBlock):
        return ParserFormulaBlock(text=block.text, format=block.format, page=block.page)
    raise ValueError(f"Unsupported parser block: {type(block).__name__}")
