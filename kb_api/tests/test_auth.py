from datetime import datetime, timedelta, timezone

import pytest

from kb_api.api.auth import create_token, decode_token, hash_password, verify_password


def test_password_is_pbkdf2_and_verifies_without_storing_plaintext():
    encoded = hash_password("correct horse")
    assert encoded.startswith("pbkdf2_sha256$")
    assert "correct horse" not in encoded
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


def test_hmac_token_rejects_tampering_and_expiry():
    token = create_token({"sub": "user-1"}, "secret", expires_in=timedelta(minutes=5))
    assert decode_token(token, "secret")["sub"] == "user-1"
    with pytest.raises(ValueError):
        decode_token(token + "x", "secret")
    expired = create_token(
        {"sub": "user-1"},
        "secret",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(ValueError):
        decode_token(expired, "secret")


def test_login_me_and_internal_verify_return_frontend_identity(system):
    client = system["client"]
    headers = system["headers"]
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["name"] == "admin"
    assert me.json()["org_id"] is None

    verified = client.get("/api/v1/auth/verify", headers=headers)
    assert verified.status_code == 200
    assert verified.json()["principal_type"] == "user"
    assert verified.headers["X-User-Id"] == system["admin"]["id"]
    assert verified.headers["X-Org-Id"] == ""
    assert "X-Node-Id" not in verified.headers


def test_login_rejects_bad_credentials(system):
    response = system["client"].post(
        "/api/v1/auth/login",
        json={"name": "admin", "password": "bad"},
    )
    assert response.status_code == 401


def test_internal_verify_validates_selected_app(system):
    first = system["client"].post(
        "/api/v1/apps", json={"name": "First", "app_id": "first"}, headers=system["headers"]
    ).json()["app"]

    verified = system["client"].get(
        "/api/v1/auth/verify",
        headers=system["headers"] | {"X-App-Id": first["app_id"]},
    )

    assert verified.status_code == 200
    assert verified.headers["X-App-Id"] == first["app_id"]


def test_internal_verify_accepts_app_api_key_as_bearer(system):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "API Client", "app_id": "api_client"}, headers=system["headers"]
    ).json()["app"]

    verified = system["client"].get(
        "/api/v1/auth/verify",
        headers={"Authorization": f"Bearer {app['api_key']}", "X-App-Id": app["app_id"]},
    )

    assert verified.status_code == 200
    assert verified.json()["principal_type"] == "api_key"
    assert verified.headers["X-App-Id"] == app["app_id"]
