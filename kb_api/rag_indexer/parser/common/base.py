from __future__ import annotations

from abc import ABC, abstractmethod

from kb_api.rag_indexer.parser.common.schema import Block


class BlockParser(ABC):
    @abstractmethod
    def parse(self, filepath: str) -> list[Block]:
        ...
