from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.api.schemas import OrgCreate, OrgUpdate
from kb_api.auth import current_user, require_admin


router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


def _visible_org(repository, user: dict, org_id: str) -> dict:
    org = repository.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    if user["role"] != "owner" and org_id not in repository.subtree_org_ids(user["org_id"]):
        raise HTTPException(status_code=404, detail="Org not found")
    return org


@router.get("")
def list_orgs(request: Request, app_id: str | None = None, include_disabled: bool = False, user=Depends(current_user)):
    repository = request.app.state.repository
    if include_disabled:
        require_admin(repository, user, user.get("org_id"))
    if app_id is not None:
        if not repository.get_app(app_id):
            raise HTTPException(status_code=404, detail="App not found")
        if user["role"] != "owner" and not any(app["id"] == app_id for app in repository.list_apps(user["org_id"])):
            raise HTTPException(status_code=403, detail="App is outside visible scope")
        if user["role"] == "owner" and not include_disabled:
            orgs = repository.list_app_orgs(app_id)
        else:
            orgs = repository.list_orgs(
                None if user["role"] == "owner" else user["org_id"],
                include_disabled=include_disabled,
            )
            orgs = [org for org in orgs if org["app_id"] == app_id]
    else:
        orgs = repository.list_orgs(
            None if user["role"] == "owner" else user["org_id"],
            include_disabled=include_disabled,
        )
    if user["role"] != "owner":
        visible_org_ids = repository.subtree_org_ids(user["org_id"])
        orgs = [org for org in orgs if org["id"] in visible_org_ids]
    return {"orgs": orgs}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_org(body: OrgCreate, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    parent = _visible_org(repository, user, body.parent_id)
    require_admin(repository, user, body.parent_id)
    if not repository.is_active_org(body.parent_id):
        raise HTTPException(status_code=409, detail="Parent org is disabled")
    return repository.create_org(parent["app_id"], parent["id"], body.name)


@router.get("/{org_id}")
def get_org(org_id: str, request: Request, user=Depends(current_user)):
    return _visible_org(request.app.state.repository, user, org_id)


@router.put("/{org_id}")
def update_org(org_id: str, body: OrgUpdate, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    org = _visible_org(repository, user, org_id)
    require_admin(repository, user, org_id)
    if org["parent_id"] is None and body.parent_id:
        raise HTTPException(status_code=409, detail="Top-level org cannot be moved")
    if "deleted_at" in body.model_fields_set and org["parent_id"] is not None and not repository.is_active_org(org["parent_id"]):
        raise HTTPException(status_code=409, detail="Parent org is disabled")
    if body.parent_id:
        parent = _visible_org(repository, user, body.parent_id)
        require_admin(repository, user, body.parent_id)
        if not repository.is_active_org(body.parent_id):
            raise HTTPException(status_code=409, detail="Parent org is disabled")
        if parent["app_id"] != org["app_id"]:
            raise HTTPException(status_code=403, detail="Parent org must belong to the same app")
        if body.parent_id in repository.subtree_org_ids(org_id):
            raise HTTPException(status_code=409, detail="Org cycle is not allowed")
    values = {}
    if "name" in body.model_fields_set:
        values["name"] = body.name
    if "parent_id" in body.model_fields_set and body.parent_id is not None:
        values["parent_id"] = body.parent_id
    if "deleted_at" in body.model_fields_set:
        values["deleted_at"] = None
    return repository.update_org(org_id, **values)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org(org_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    org = _visible_org(repository, user, org_id)
    require_admin(repository, user, org_id)
    if org["parent_id"] is None:
        raise HTTPException(status_code=409, detail="Top-level org cannot be disabled")
    if org_id == user.get("org_id"):
        raise HTTPException(status_code=409, detail="Current user's org cannot be disabled")
    if not repository.delete_org(org_id):
        raise HTTPException(status_code=404, detail="Org not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{org_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def purge_org(org_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    org = _visible_org(repository, user, org_id)
    require_admin(repository, user, org_id)
    if org["parent_id"] is None:
        raise HTTPException(status_code=409, detail="Top-level org cannot be removed")
    if not org.get("deleted_at") or not repository.purge_org(org_id):
        raise HTTPException(status_code=409, detail="Only empty disabled orgs can be removed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
