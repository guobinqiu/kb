from dataclasses import dataclass, field

from kb_api.rag_indexer.parser.common.contracts import TextKind


@dataclass
class TextBlock:
    text: str
    page: int | None = None
    kind: TextKind = "text"
    level: int | None = None


@dataclass
class TableBlock:
    rows: list[list[str]] = field(default_factory=list)
    caption: str = ""
    page: int | None = None


@dataclass
class FormulaBlock:
    text: str
    format: str = "latex"
    page: int | None = None


Block = TextBlock | TableBlock | FormulaBlock
