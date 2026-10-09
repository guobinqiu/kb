from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.api.permissions import require_admin
from kb_api.api.schemas import UserCreate, UserUpdate
from kb_api.api.auth import current_user, hash_password


router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _public(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


def _visible(dao, actor: dict, found: dict | None) -> bool:
    if not found:
        return False
    if actor["role"] == "owner":
        return True
    org_id = found.get("org_id")
    return bool(org_id and org_id in dao.subtree_org_ids(actor["org_id"]))


def _require_active_org(dao, actor: dict, org_id: str) -> None:
    require_admin(dao, actor, org_id)
    if not dao.get_org(org_id):
        raise HTTPException(status_code=404, detail="Org not found")
    if not dao.is_active_org(org_id):
        raise HTTPException(status_code=409, detail="Org is disabled")


@router.get("")
def list_users(request: Request, org_id: str | None = None, include_disabled: bool = False, user=Depends(current_user)):
    dao = request.app.state.dao
    selected_org_id = org_id if org_id is not None else user.get("org_id")
    if user["role"] != "owner" and selected_org_id not in dao.subtree_org_ids(user["org_id"]):
        raise HTTPException(status_code=403, detail="Org is outside visible scope")
    if include_disabled:
        require_admin(dao, user, selected_org_id)
    users = dao.list_users(selected_org_id, include_disabled=include_disabled)
    if user["role"] == "owner" and not include_disabled:
        users = [item for item in users if item.get("org_id") is None or dao.is_active_org(item["org_id"])]
    return {"users": users}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    if body.role == "owner":
        if user["role"] != "owner":
            raise HTTPException(status_code=403, detail="Only owner can grant owner")
    else:
        _require_active_org(dao, user, body.org_id)
    try:
        created = dao.create_user(
            org_id=body.org_id,
            name=body.name,
            password_hash=hash_password(body.password),
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public(created)


@router.get("/{user_id}")
def get_user(user_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    found = dao.get_user(user_id)
    if not _visible(dao, user, found):
        raise HTTPException(status_code=404, detail="User not found")
    if user["role"] == "member" and (
        found.get("deleted_at") or not dao.is_active_org(found["org_id"])
    ):
        raise HTTPException(status_code=404, detail="User not found")
    return _public(found)


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    found = dao.get_user(user_id)
    if not _visible(dao, user, found):
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == user["id"]:
        raise HTTPException(status_code=409, detail="Current user cannot be modified here")
    if user["role"] != "owner":
        require_admin(dao, user, found.get("org_id"))
    desired_role = body.role if "role" in body.model_fields_set else found["role"]
    desired_org_id = body.org_id if "org_id" in body.model_fields_set else found.get("org_id")
    if (desired_role == "owner") != (desired_org_id is None):
        raise HTTPException(status_code=409, detail="Owner must not belong to an org and other roles require org_id")
    if desired_role == "owner" and user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner can grant owner")
    if desired_org_id is not None:
        _require_active_org(dao, user, desired_org_id)
    values = {}
    if "org_id" in body.model_fields_set:
        values["org_id"] = body.org_id
    if body.password:
        values["password_hash"] = hash_password(body.password)
    if "role" in body.model_fields_set:
        values["role"] = body.role
    if "deleted_at" in body.model_fields_set:
        values["deleted_at"] = None
    return _public(dao.update_user(user_id, **values))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    found = dao.get_user(user_id)
    if not _visible(dao, user, found):
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == user["id"]:
        raise HTTPException(status_code=409, detail="Current user cannot be deleted")
    if user["role"] != "owner":
        require_admin(dao, user, found.get("org_id"))
    if found["role"] == "owner" and user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner can manage owner")
    dao.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
