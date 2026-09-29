from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response

from kb_api.api.auth import create_token, resolve_principal, verify_password, hash_password
from kb_api.api.schemas import LoginRequest, PasswordChange


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


@router.post("/login")
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


@router.get("/verify")
def verify(request: Request, response: Response):
    dao = request.app.state.dao
    principal = resolve_principal(request)
    requested_app_id = request.headers.get("X-App-Id")
    if requested_app_id:
        if principal["principal_type"] == "api_key":
            allowed = principal["app_id"] == requested_app_id
        else:
            allowed = any(
                app["app_id"] == requested_app_id
                for app in dao.list_apps(
                    None if principal["user"]["role"] == "owner" else principal["org_id"]
                )
            )
        if not allowed:
            raise HTTPException(status_code=403, detail="App is outside visible scope")
        principal["app_id"] = requested_app_id
    requested_org_id = request.headers.get("X-Org-Id")
    if requested_org_id:
        org = dao.get_org(requested_org_id)
        app = dao.get_app(org["app_id"]) if org and dao.is_active_org(requested_org_id) else None
        if not app or (principal.get("app_id") and app["app_id"] != principal["app_id"]):
            raise HTTPException(status_code=403, detail="Org is outside visible scope")
        if principal["principal_type"] == "user" and principal["user"]["role"] != "owner":
            if requested_org_id not in dao.subtree_org_ids(principal["org_id"]):
                raise HTTPException(status_code=403, detail="Org is outside visible scope")
        principal["app_id"] = app["app_id"]
        principal["org_id"] = requested_org_id
    requested_workspace_id = request.headers.get("X-Workspace-Id")
    if requested_workspace_id:
        workspace = dao.get_workspace(requested_workspace_id)
        app = dao.get_app(workspace["app_id"]) if workspace else None
        if not app or app["app_id"] != principal.get("app_id"):
            raise HTTPException(status_code=403, detail="Workspace is outside visible scope")
        if principal["principal_type"] == "user" and not dao.has_workspace_access(principal["user"], requested_workspace_id):
            raise HTTPException(status_code=403, detail="Workspace is outside visible scope")
    headers = {
        "X-Principal-Type": principal["principal_type"],
        "X-App-Id": principal.get("app_id") or "",
        "X-User-Id": principal.get("user_id") or "",
        "X-Org-Id": principal.get("org_id") or "",
    }
    for key, value in headers.items():
        response.headers[key] = value
    return principal | {"user": _public_user(principal["user"])} if principal["principal_type"] == "user" else principal
