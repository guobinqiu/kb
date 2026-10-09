from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request


PBKDF2_ITERATIONS = 260_000


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64decode(salt), int(iterations))
        return hmac.compare_digest(_b64encode(digest), expected)
    except (ValueError, TypeError):
        return False


def create_token(
    claims: dict,
    secret: str,
    *,
    expires_in: timedelta = timedelta(days=1),
    expires_at: datetime | None = None,
) -> str:
    payload = dict(claims)
    expiry = expires_at or datetime.now(timezone.utc) + expires_in
    payload["exp"] = expiry
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if not isinstance(payload, dict):
            raise ValueError("invalid token payload")
        return payload
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise ValueError("invalid token") from exc


def authenticate_request(request: Request) -> dict:
    api_key = request.headers.get("X-API-Key")
    authorization = request.headers.get("Authorization", "")
    if api_key and authorization.startswith("Bearer "):
        raise HTTPException(status_code=400, detail="Use either user token or API key")
    if api_key:
        app = request.app.state.dao.get_app_by_api_key(api_key)
        if not app:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        requested_app_id = request.headers.get("X-App-Id")
        if not requested_app_id:
            raise HTTPException(status_code=400, detail="X-App-Id is required")
        if app["app_id"] != requested_app_id:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {"principal_type": "api_key", "app_id": app["app_id"], "user_id": None, "org_id": None}

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    bearer = authorization[7:]
    try:
        claims = decode_token(bearer, request.app.state.token_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = request.app.state.dao.get_user(claims.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    if user.get("deleted_at"):
        raise HTTPException(status_code=401, detail="Account disabled")
    org_id = user.get("org_id")
    if user["role"] != "owner" and (not org_id or not request.app.state.dao.is_active_org(org_id)):
        raise HTTPException(status_code=401, detail="Account disabled")
    org = request.app.state.dao.get_org(org_id) if org_id else None
    return {
        "principal_type": "user",
        "app_id": request.app.state.dao.get_app(org["app_id"])["app_id"] if org else None,
        "user_id": user["id"],
        "org_id": org_id,
        "user": user,
    }


def resolve_principal(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return principal
    authentication_error = getattr(request.state, "authentication_error", None)
    if authentication_error is not None:
        raise HTTPException(status_code=authentication_error[0], detail=authentication_error[1])
    principal = authenticate_request(request)
    request.state.principal = principal
    return principal


def current_user(request: Request) -> dict:
    principal = resolve_principal(request)
    if principal["principal_type"] != "user":
        raise HTTPException(status_code=403, detail="User token required")
    return principal["user"]
