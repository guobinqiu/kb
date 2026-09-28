import re
import unicodedata


def clean_cjk_spaces(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", text)


def split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text) if paragraph.strip()]
