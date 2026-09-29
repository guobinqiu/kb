from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar


APP_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")


def validate_app_id(app_id: str) -> str:
    if not APP_ID_PATTERN.fullmatch(app_id):
        raise ValueError("app_id must start with a letter and contain only letters, numbers, or underscore")
    return app_id


_current_app_id: ContextVar[str | None] = ContextVar("current_app_id", default=None)


def collection_name_for_app(app_id: str) -> str:
    validated = validate_app_id(app_id)
    return f"{validated}_chunks"


def current_collection() -> str:
    app_id = _current_app_id.get()
    if app_id is None:
        raise RuntimeError("app collection scope is required")
    return collection_name_for_app(app_id)


@contextmanager
def app_collection(app_id: str):
    validate_app_id(app_id)
    token = _current_app_id.set(app_id)
    try:
        yield
    finally:
        _current_app_id.reset(token)
