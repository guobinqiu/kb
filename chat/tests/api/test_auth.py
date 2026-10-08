import asyncio
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from chat.src.api.auth import require_user_principal


def _token(claims: dict, secret: str = "test-secret") -> str:
    payload = dict(claims)
    payload.setdefault("exp", int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()))
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


def test_chat_requires_bearer_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_user_principal())

    assert exc.value.status_code == 401


def test_chat_validates_user_token_locally():
    principal = asyncio.run(
        require_user_principal(
            authorization=f"Bearer {_token({'sub': 'user-1'})}",
            x_app_id="app-id",
        )
    )

    assert principal.app_id == "app-id"
    assert principal.user_id == "user-1"


def test_chat_rejects_invalid_token_signature():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_user_principal(
            authorization=f"Bearer {_token({'sub': 'user-1'}, 'wrong-secret')}",
            x_app_id="app-id",
        ))

    assert exc.value.status_code == 401


def test_chat_rejects_expired_token():
    expired = int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_user_principal(
            authorization=f"Bearer {_token({'sub': 'user-1', 'exp': expired})}",
            x_app_id="app-id",
        ))

    assert exc.value.status_code == 401
