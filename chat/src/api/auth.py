"""API authentication helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import Header, HTTPException

from chat.src.config import settings


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    api_key: str
    user_id: str = ""


@dataclass(frozen=True)
class Principal:
    type: Literal["user"]
    app_id: str
    user_id: str


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


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _decode_token(token: str) -> dict:
    try:
        encoded, signature = token.split(".", 1)
        expected = base64.urlsafe_b64encode(
            hmac.new(settings.token_secret.encode(), encoded.encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid token signature")
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict) or int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("token expired")
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            raise ValueError("token subject is required")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def require_user_principal(
    authorization: str | None = Header(None),
    x_app_id: str | None = Header(None),
):
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if not isinstance(x_app_id, str) or not x_app_id:
        raise HTTPException(status_code=400, detail="X-App-Id is required")
    claims = _decode_token(authorization[7:])
    user_id = claims["sub"]
    _current_credential.set(AppCredential(app_id=x_app_id, api_key="", user_id=user_id))
    return Principal(type="user", app_id=x_app_id, user_id=user_id)
