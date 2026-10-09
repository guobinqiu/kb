from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.api.permissions import require_admin
from kb_api.api.schemas import OrgCreate, OrgUpdate
from kb_api.api.auth import current_user


router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


def _visible_org(dao, user: dict, org_id: str) -> dict:
    org = dao.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    if user["role"] != "owner" and org_id not in dao.subtree_org_ids(user["org_id"]):
        raise HTTPException(status_code=404, detail="Org not found")
    return org


@router.get("")
def list_orgs(request: Request, app_id: str | None = None, include_disabled: bool = False, user=Depends(current_user)):
    dao = request.app.state.dao
    if include_disabled:
        require_admin(dao, user, user.get("org_id"))
    if app_id is not None:
        app = dao.get_app_by_business_id(app_id)
        if not app:
            raise HTTPException(status_code=404, detail="App not found")
        if user["role"] != "owner" and not any(item["id"] == app["id"] for item in dao.list_apps(user["org_id"])):
            raise HTTPException(status_code=403, detail="App is outside visible scope")
        if user["role"] == "owner" and not include_disabled:
            orgs = dao.list_app_orgs(app["id"])
        else:
            orgs = dao.list_orgs(
                None if user["role"] == "owner" else user["org_id"],
                include_disabled=include_disabled,
            )
            orgs = [org for org in orgs if org["app_id"] == app["id"]]
    else:
        orgs = dao.list_orgs(
            None if user["role"] == "owner" else user["org_id"],
            include_disabled=include_disabled,
        )
    return {"orgs": orgs}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_org(body: OrgCreate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    parent = _visible_org(dao, user, body.parent_id)
    require_admin(dao, user, body.parent_id)
    if not dao.is_active_org(body.parent_id):
        raise HTTPException(status_code=409, detail="Parent org is disabled")
    return dao.create_org(parent["app_id"], parent["id"], body.name)


@router.get("/{org_id}")
def get_org(org_id: str, request: Request, user=Depends(current_user)):
    return _visible_org(request.app.state.dao, user, org_id)


@router.patch("/{org_id}")
def update_org(org_id: str, body: OrgUpdate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    org = _visible_org(dao, user, org_id)
    require_admin(dao, user, org_id)
    if org["parent_id"] is None and body.parent_id:
        raise HTTPException(status_code=409, detail="Top-level org cannot be moved")
    if "deleted_at" in body.model_fields_set and org["parent_id"] is not None and not dao.is_active_org(org["parent_id"]):
        raise HTTPException(status_code=409, detail="Parent org is disabled")
    if body.parent_id:
        parent = _visible_org(dao, user, body.parent_id)
        require_admin(dao, user, body.parent_id)
        if not dao.is_active_org(body.parent_id):
            raise HTTPException(status_code=409, detail="Parent org is disabled")
        if parent["app_id"] != org["app_id"]:
            raise HTTPException(status_code=403, detail="Parent org must belong to the same app")
        if body.parent_id in dao.subtree_org_ids(org_id):
            raise HTTPException(status_code=409, detail="Org cycle is not allowed")
    values = {}
    if "name" in body.model_fields_set:
        values["name"] = body.name
    if "parent_id" in body.model_fields_set and body.parent_id is not None:
        values["parent_id"] = body.parent_id
    if "deleted_at" in body.model_fields_set:
        values["deleted_at"] = None
    return dao.update_org(org_id, **values)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org(org_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    org = _visible_org(dao, user, org_id)
    require_admin(dao, user, org_id)
    if org["parent_id"] is None:
        raise HTTPException(status_code=409, detail="Top-level org cannot be disabled")
    if org_id == user.get("org_id"):
        raise HTTPException(status_code=409, detail="Current user's org cannot be disabled")
    if not dao.delete_org(org_id):
        raise HTTPException(status_code=404, detail="Org not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
