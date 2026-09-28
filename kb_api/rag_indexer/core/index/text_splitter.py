from collections import deque
import re


_BOUNDARIES = tuple(re.compile(pattern) for pattern in (
    r"\n[ \t]*\n+", "\n", r"[。！？!?]|\.(?=\s|$)", r"[；;]", r"[，,]", r"[ \t]+",
)) + (None,)


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if overlap < 0:
        raise ValueError(f"chunk_overlap must be >= 0, got {overlap}")
    if overlap > chunk_size:
        raise ValueError(f"Got a larger chunk overlap ({overlap}) than chunk size ({chunk_size}), should be smaller.")
    return _split(text, chunk_size, overlap, _BOUNDARIES)


def _split(text: str, chunk_size: int, overlap: int, boundaries: tuple[re.Pattern[str] | None, ...]) -> list[str]:
    for index, boundary in enumerate(boundaries):
        if boundary is None or boundary.search(text):
            break
    remaining = boundaries[index + 1:]
    if boundary is None:
        parts = list(text)
    else:
        parts = []
        start = 0
        for match in boundary.finditer(text):
            parts.append(text[start:match.end()])
            start = match.end()
        if start < len(text):
            parts.append(text[start:])

    chunks = []
    pending = []
    for part in parts:
        if len(part) < chunk_size:
            pending.append(part)
            continue
        if pending:
            chunks.extend(_merge(pending, chunk_size, overlap))
            pending = []
        if remaining:
            chunks.extend(_split(part, chunk_size, overlap, remaining))
        else:
            chunks.append(part)
    if pending:
        chunks.extend(_merge(pending, chunk_size, overlap))
    return chunks


def _merge(parts: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    window = deque()
    length = 0
    for part in parts:
        if window and length + len(part) > chunk_size:
            text = "".join(window).strip()
            if text:
                chunks.append(text)
            # Retain whole boundary fragments, rather than cutting the overlap mid-sentence.
            while window and (length > overlap or length + len(part) > chunk_size):
                length -= len(window.popleft())
        window.append(part)
        length += len(part)
    text = "".join(window).strip()
    if text:
        chunks.append(text)
    return chunks
