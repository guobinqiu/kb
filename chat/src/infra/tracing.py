from contextvars import ContextVar, Token
from uuid import uuid4

_thread_id: ContextVar[str | None] = ContextVar("thread_id", default=None)
_request_trace_id: ContextVar[str | None] = ContextVar("request_trace_id", default=None)


def get_trace_id() -> str:
    return _request_trace_id.get() or "-"


def start_request_trace(_headers) -> Token:
    return _request_trace_id.set(uuid4().hex)


def reset_request_trace(token: Token) -> None:
    _request_trace_id.reset(token)


def set_thread_id(thread_id: str | None = None) -> str | None:
    _thread_id.set(thread_id)
    return thread_id


def get_thread_id() -> str | None:
    return _thread_id.get()
