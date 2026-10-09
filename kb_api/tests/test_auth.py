from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from kb_api.api.auth import create_token, decode_token, hash_password, verify_password
from kb_api.api.config import Settings
from kb_api.api.rate_limit import _requests


def test_password_is_pbkdf2_and_verifies_without_storing_plaintext():
    encoded = hash_password("correct horse")
    assert encoded.startswith("pbkdf2_sha256$")
    assert "correct horse" not in encoded
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


def test_settings_read_jwt_secret(monkeypatch):
    monkeypatch.setenv("KB_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("JWT_SECRET", "jwt-key")

    settings = Settings.from_env()
    assert settings.token_secret == "jwt-key"


@pytest.mark.parametrize("name", ["JWT_SECRET", "KB_ADMIN_PASSWORD"])
def test_settings_require_security_credentials(monkeypatch, name):
    monkeypatch.setenv("JWT_SECRET", "jwt-key")
    monkeypatch.setenv("KB_ADMIN_PASSWORD", "admin-password")
    monkeypatch.delenv(name)

    with pytest.raises(ValueError, match=name):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JWT_SECRET", "change-me"),
        ("KB_ADMIN_PASSWORD", "admin"),
        ("KB_ADMIN_PASSWORD", "change-me"),
    ],
)
def test_settings_reject_unsafe_security_credentials(monkeypatch, name, value):
    monkeypatch.setenv("JWT_SECRET", "jwt-key")
    monkeypatch.setenv("KB_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_jwt_token_rejects_tampering_and_expiry():
    secret = "test-secret-at-least-32-bytes-long"
    token = create_token({"sub": "user-1"}, secret, expires_in=timedelta(minutes=5))
    assert token.count(".") == 2
    assert decode_token(token, secret)["sub"] == "user-1"
    with pytest.raises(ValueError):
        decode_token(token + "x", secret)
    expired = create_token(
        {"sub": "user-1"},
        secret,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(ValueError):
        decode_token(expired, secret)


def test_login_me_returns_frontend_identity(system):
    client = system["client"]
    headers = system["headers"]
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["name"] == "admin"
    assert me.json()["org_id"] is None


def test_login_rejects_bad_credentials(system):
    response = system["client"].post(
        "/api/v1/auth/login",
        json={"name": "admin", "password": "bad"},
    )
    assert response.status_code == 401


def test_login_is_rate_limited_by_client(system):
    _requests.clear()
    system["client"].app.state.api_limits = SimpleNamespace(rate_limit="2/minute")

    for _ in range(2):
        response = system["client"].post(
            "/api/v1/auth/login",
            json={"name": "admin", "password": "bad"},
        )
        assert response.status_code == 401

    response = system["client"].post(
        "/api/v1/auth/login",
        json={"name": "admin", "password": "bad"},
    )
    assert response.status_code == 429


def test_rag_config_rejects_app_api_key_as_bearer(system):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "API Client", "app_id": "api_client"}, headers=system["headers"]
    ).json()["app"]

    verified = system["client"].get(
        "/api/v1/rag/config",
        headers={"Authorization": f"Bearer {app['api_key']}", "X-App-Id": app["app_id"]},
    )

    assert verified.status_code == 401


def test_app_api_key_must_match_requested_app(system):
    first = system["client"].post(
        "/api/v1/apps", json={"name": "First", "app_id": "first_app"}, headers=system["headers"]
    ).json()["app"]
    second = system["client"].post(
        "/api/v1/apps", json={"name": "Second", "app_id": "second_app"}, headers=system["headers"]
    ).json()["app"]

    response = system["client"].get(
        "/api/v1/rag/config",
        headers={"X-API-Key": first["api_key"], "X-App-Id": second["app_id"]},
    )

    assert response.status_code == 401


def test_request_rejects_mixed_user_token_and_api_key(system):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "Mixed", "app_id": "mixed_app"}, headers=system["headers"]
    ).json()["app"]

    response = system["client"].get(
        "/api/v1/rag/config",
        headers=system["headers"] | {"X-App-Id": app["app_id"], "X-API-Key": app["api_key"]},
    )

    assert response.status_code == 400
