"""请求级模型选择。

使用 ContextVar 保存本次请求指定的模型，避免把参数逐层透传到每个
graph/node 调用点。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_request_model_name: ContextVar[str | None] = ContextVar("request_model_name", default=None)


def get_request_model_name() -> str | None:
    """获取当前请求指定的模型名。"""
    v = _request_model_name.get()
    return v or None


@contextmanager
def bind_request_model_name(model_name: str | None):
    """在代码块作用域内绑定当前请求指定的模型名。"""
    model_name = (model_name or "").strip() or None
    token = _request_model_name.set(model_name)
    try:
        yield
    finally:
        _request_model_name.reset(token)
