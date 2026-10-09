"""API authentication helpers."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

import jwt
from fastapi import Header, HTTPException, Request

from chat.src.config import settings


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    api_key: str
    user_id: str = ""


@dataclass(frozen=True)
class Principal:
    type: Literal["user", "api_key"]
    app_id: str
    user_id: str = ""
    api_key: str = ""


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


def set_current_credential(principal: Principal) -> Token:
    return _current_credential.set(AppCredential(
        app_id=principal.app_id,
        api_key=principal.api_key,
        user_id=principal.user_id,
    ))


def reset_current_credential(token: Token) -> None:
    _current_credential.reset(token)


def principal_metadata(principal: Principal) -> dict[str, str]:
    return {
        "app_id": principal.app_id,
        "principal_type": principal.type,
        "principal_id": principal.user_id or "app",
    }


def scoped_thread_id(principal: Principal, thread_id: str) -> str:
    metadata = principal_metadata(principal)
    scope = ":".join((
        metadata["app_id"],
        metadata["principal_type"],
        metadata["principal_id"],
        thread_id,
    ))
    return hashlib.sha256(scope.encode()).hexdigest()


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.token_secret, algorithms=["HS256"])
        if not isinstance(payload, dict):
            raise ValueError("invalid token payload")
        if not isinstance(payload.get("sub"), str) or not payload["sub"]:
            raise ValueError("token subject is required")
        return payload
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def _validate_app_credential(request: Request, app_id: str, api_key: str) -> None:
    pool = getattr(request.app.state, "auth_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Authentication database unavailable")
    async with pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT app_id FROM apps WHERE app_id = %s AND api_key = %s",
            (app_id, api_key),
        )
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")


async def authenticate_request(
    request: Request,
    authorization: str | None = Header(None),
    x_app_id: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> Principal:
    has_bearer = isinstance(authorization, str) and authorization.startswith("Bearer ")
    has_api_key = isinstance(x_api_key, str) and bool(x_api_key)
    if has_api_key and has_bearer:
        raise HTTPException(status_code=400, detail="Use either user token or API key")
    if not has_api_key and not has_bearer:
        raise HTTPException(status_code=401, detail="Missing credentials")
    if not isinstance(x_app_id, str) or not x_app_id:
        raise HTTPException(status_code=400, detail="X-App-Id is required")
    if has_api_key:
        await _validate_app_credential(request, x_app_id, x_api_key)
        return Principal(type="api_key", app_id=x_app_id, api_key=x_api_key)
    bearer = authorization[7:]
    claims = _decode_token(bearer)
    return Principal(type="user", app_id=x_app_id, user_id=claims["sub"])


async def require_principal(
    request: Request,
    authorization: str | None = Header(None),
    x_app_id: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        authentication_error = getattr(request.state, "authentication_error", None)
        if authentication_error is not None:
            raise HTTPException(status_code=authentication_error[0], detail=authentication_error[1])
        principal = await authenticate_request(request, authorization, x_app_id, x_api_key)
        request.state.principal = principal
    return principal


class AuthenticationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if request.headers.get("Authorization") or request.headers.get("X-API-Key"):
            try:
                scope.setdefault("state", {})["principal"] = await authenticate_request(
                    request,
                    request.headers.get("Authorization"),
                    request.headers.get("X-App-Id"),
                    request.headers.get("X-API-Key"),
                )
            except HTTPException as exc:
                scope.setdefault("state", {})["authentication_error"] = (exc.status_code, exc.detail)
        await self.app(scope, receive, send)
