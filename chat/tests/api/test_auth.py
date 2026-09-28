import asyncio

import pytest
from fastapi import HTTPException

from chat.src.api.auth import require_api_key


def test_chat_requires_trusted_gateway_identity():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_api_key())

    assert exc.value.status_code == 401


def test_chat_accepts_trusted_gateway_identity():
    principal = asyncio.run(
        require_api_key(
            x_principal_type="user",
            x_app_id="app-id",
        )
    )

    assert principal.app_id == "app-id"
