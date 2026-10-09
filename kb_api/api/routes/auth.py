from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from kb_api.api.auth import create_token, resolve_principal, verify_password, hash_password
from kb_api.api.rate_limit import require_rate_limit
from kb_api.api.schemas import LoginRequest, PasswordChange


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


@router.post("/login", dependencies=[Depends(require_rate_limit)])
def login(body: LoginRequest, request: Request):
    dao = request.app.state.dao
    user = dao.get_user_by_name(body.name)
    if not user or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("deleted_at") or (
        user["role"] != "owner" and (
            not user.get("org_id") or not dao.is_active_org(user["org_id"])
        )
    ):
        raise HTTPException(status_code=401, detail="Account disabled")
    token = create_token(
        {"sub": user["id"]},
        request.app.state.token_secret,
        expires_in=timedelta(seconds=request.app.state.token_ttl_seconds),
    )
    return {"access_token": token, "user": _public_user(user)}


@router.get("/me")
def me(request: Request):
    principal = resolve_principal(request)
    if principal["principal_type"] != "user":
        raise HTTPException(status_code=403, detail="User token required")
    return _public_user(principal["user"]) | {
        "is_platform_admin": principal["user"]["role"] == "owner",
    }


@router.patch("/password")
def change_password(body: PasswordChange, request: Request):
    dao = request.app.state.dao
    principal = resolve_principal(request)
    if principal["principal_type"] != "user":
        raise HTTPException(status_code=403, detail="User token required")
    user = principal["user"]
    if not verify_password(body.old_password, user.get("password_hash")):
        raise HTTPException(status_code=403, detail="Invalid current password")
    dao.update_user(user["id"], password_hash=hash_password(body.new_password))
    return {"success": True}
