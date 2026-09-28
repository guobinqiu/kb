"""API authentication helpers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    api_key: str


@dataclass(frozen=True)
class Principal:
    type: Literal["admin", "app"]
    app_id: str


_current_credential: ContextVar[AppCredential | None] = ContextVar("current_credential", default=None)
_current_authorization: ContextVar[str | None] = ContextVar(
    "current_authorization", default=None
)


def get_current_credential() -> AppCredential | None:
    return _current_credential.get()


def get_current_authorization() -> str | None:
    return _current_authorization.get()


def set_current_authorization(value: str | None) -> Token:
    return _current_authorization.set(value)


def reset_current_authorization(token: Token) -> None:
    _current_authorization.reset(token)


async def require_api_key(
    x_principal_type: str | None = Header(None),
    x_app_id: str | None = Header(None),
):
    if x_principal_type in {"user", "api_key"} and x_app_id:
        credential = AppCredential(app_id=x_app_id, api_key="")
        _current_credential.set(credential)
        return Principal(type="app", app_id=x_app_id)
    raise HTTPException(401, "trusted gateway identity is required")
