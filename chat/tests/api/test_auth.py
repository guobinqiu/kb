from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from chat.src.api.auth import require_principal


class FakeConnection:
    def __init__(self, app_id: str | None):
        self.app_id = app_id
        self.params = None

    async def execute(self, _query, params):
        self.params = params
        return self

    async def fetchone(self):
        return {"app_id": self.app_id} if self.app_id else None


class FakePool:
    def __init__(self, app_id: str | None):
        self.connection_instance = FakeConnection(app_id)

    @asynccontextmanager
    async def connection(self):
        yield self.connection_instance


def _request(app_id: str | None) -> Request:
    request = Request({"type": "http", "app": None, "headers": []})
    request.scope["app"] = type("App", (), {"state": type("State", (), {})()})()
    request.app.state.auth_pool = FakePool(app_id)
    return request


def _token(claims: dict, secret: str = "test-secret-at-least-32-bytes-long") -> str:
    payload = dict(claims)
    payload.setdefault("exp", int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()))
    return jwt.encode(payload, secret, algorithm="HS256")


async def test_chat_requires_app_id_and_api_key():
    with pytest.raises(HTTPException) as exc:
        await require_principal(_request(None))

    assert exc.value.status_code == 401


async def test_chat_validates_app_id_and_api_key():
    request = _request("app-id")

    principal = await require_principal(
        request,
        x_app_id="app-id",
        x_api_key="app-key",
    )

    assert principal.app_id == "app-id"
    assert request.app.state.auth_pool.connection_instance.params == ("app-id", "app-key")


async def test_chat_rejects_bearer_app_api_key():
    with pytest.raises(HTTPException) as exc:
        await require_principal(
            _request("app-id"),
            authorization="Bearer app-key",
            x_app_id="app-id",
        )

    assert exc.value.status_code == 401


async def test_chat_accepts_user_bearer_token():
    principal = await require_principal(
        _request(None),
        authorization=f"Bearer {_token({'sub': 'user-1'})}",
        x_app_id="app-id",
    )

    assert principal.type == "user"
    assert principal.app_id == "app-id"
    assert principal.user_id == "user-1"


async def test_chat_rejects_mismatched_app_credentials():
    with pytest.raises(HTTPException) as exc:
        await require_principal(
            _request(None),
            x_app_id="other-app",
            x_api_key="app-key",
        )

    assert exc.value.status_code == 401


async def test_chat_rejects_mixed_user_token_and_api_key():
    with pytest.raises(HTTPException) as exc:
        await require_principal(
            _request("app-id"),
            authorization=f"Bearer {_token({'sub': 'user-1'})}",
            x_app_id="app-id",
            x_api_key="app-key",
        )

    assert exc.value.status_code == 400
