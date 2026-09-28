class InvalidDocumentError(ValueError):
    pass


def validate_pdf_file(filepath: str) -> None:
    import pymupdf

    try:
        with pymupdf.open(filepath):
            pass
    except Exception as exc:
        raise InvalidDocumentError("Invalid pdf file") from exc
