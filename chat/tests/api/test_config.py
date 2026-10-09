import pytest
from pydantic import ValidationError

from chat.src.config import Settings


def test_settings_accept_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "key")

    assert Settings().token_secret == "key"


def test_settings_reject_unsafe_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "change-me")

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings()
