from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from kb_api.rag_indexer.core.auth import validate_app_id


_current_app_id: ContextVar[str | None] = ContextVar("current_app_id", default=None)


def collection_name_for_app(app_id: str) -> str:
    validated = validate_app_id(app_id)
    return f"{validated}_chunks"


def current_collection() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection scope is required")
    return collection_name_for_app(app_id)


def current_app_id() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection scope is required")
    return app_id


@contextmanager
def app_collection(app_id: str):
    validate_app_id(app_id)
    token = _current_app_id.set(app_id)
    try:
        yield
    finally:
        _current_app_id.reset(token)
