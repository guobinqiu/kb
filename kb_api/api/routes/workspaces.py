from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from kb_api.api.schemas import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)
from kb_api.api.auth import current_user
from kb_api.api.permissions import (
    WORKSPACE_CREATE,
    WORKSPACE_DELETE,
    WORKSPACE_MEMBERS_MANAGE,
    WORKSPACE_UPDATE,
    can_create_workspace,
    has_workspace_permission,
    workspace_permissions,
)

apps_router = APIRouter(prefix="/api/v1/apps", tags=["workspaces"])
router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _workspace(dao, workspace_id: str, user: dict) -> dict:
    workspace = dao.get_workspace(workspace_id)
    if not workspace or not dao.has_workspace_access(user, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _member_org(dao, workspace: dict, org_id: str | None) -> dict:
    org = dao.get_org(org_id) if org_id else None
    if not org or org["app_id"] != workspace["app_id"] or not dao.is_active_org(org["id"]):
        raise HTTPException(status_code=422, detail="Org must belong to the workspace app")
    return org


def _managed_workspace(dao, workspace_id: str, user: dict) -> dict:
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_MEMBERS_MANAGE):
        raise HTTPException(status_code=403, detail="Workspace member management denied")
    return workspace


@apps_router.get("/{app_id}/workspaces")
def list_workspaces(app_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    app = dao.get_app_by_business_id(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    org = dao.get_org(user["org_id"]) if user.get("org_id") else None
    if user["role"] != "owner" and (not org or org["app_id"] != app["id"]):
        raise HTTPException(status_code=404, detail="App not found")
    workspaces = dao.list_workspaces(app["id"])
    workspaces = [
        {**item, "role": dao.get_workspace_role(user, item["id"]),
         "permissions": workspace_permissions(dao, user, item)}
        for item in workspaces if dao.has_workspace_access(user, item["id"])
    ]
    return {"workspaces": workspaces, "permissions": {WORKSPACE_CREATE: can_create_workspace(dao, user, app["id"])}}


@apps_router.post("/{app_id}/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(app_id: str, body: WorkspaceCreate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    app = dao.get_app_by_business_id(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if not can_create_workspace(dao, user, app["id"]):
        raise HTTPException(status_code=403, detail="Workspace creation denied")
    return {"workspace": dao.create_workspace(app["id"], body.name, creator_id=user["id"])}


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    return {"workspace": workspace, "role": dao.get_workspace_role(user, workspace_id),
            "permissions": workspace_permissions(dao, user, workspace)}


@router.patch("/{workspace_id}")
def update_workspace(workspace_id: str, body: WorkspaceUpdate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_UPDATE):
        raise HTTPException(status_code=403, detail="Administrator required")
    return {"workspace": dao.update_workspace(workspace_id, body.name)}


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = dao.get_workspace(workspace_id) if user["role"] == "owner" else _workspace(dao, workspace_id, user)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_DELETE):
        raise HTTPException(status_code=403, detail="Administrator required")
    if dao.list_workspace_files(workspace_id):
        raise HTTPException(status_code=409, detail="Workspace contains files")
    try:
        dao.delete_workspace(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members")
def list_members(workspace_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    _workspace(dao, workspace_id, user)
    return {"members": dao.list_workspace_members(workspace_id)}


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(workspace_id: str, body: WorkspaceMemberCreate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _managed_workspace(dao, workspace_id, user)
    if body.type == "org":
        _member_org(dao, workspace, body.id)
        return {"member": dao.add_workspace_org(workspace_id, org_id=body.id, role=body.role)}
    member_user = dao.get_user(body.id)
    if not member_user or member_user.get("deleted_at") or not member_user.get("org_id"):
        raise HTTPException(status_code=422, detail="User must belong to the workspace app")
    _member_org(dao, workspace, member_user["org_id"])
    try:
        return {"member": dao.add_workspace_member(workspace_id, user_id=body.id, role=body.role)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{workspace_id}/orgs")
def list_orgs(workspace_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _managed_workspace(dao, workspace_id, user)
    return {"orgs": dao.list_app_orgs(workspace["app_id"])}


@router.get("/{workspace_id}/users")
def list_users(
    workspace_id: str, request: Request, org_id: UUID | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    query: str = Query(default="", max_length=200), user=Depends(current_user),
):
    dao = request.app.state.dao
    workspace = _managed_workspace(dao, workspace_id, user)
    selected_org = str(org_id) if org_id is not None else None
    if selected_org is not None:
        _member_org(dao, workspace, selected_org)
    return dao.list_workspace_users(
        workspace_id, org_id=selected_org, query=query.strip(), page=page, page_size=page_size,
    )


@router.put("/{workspace_id}/members/{member_id}")
def update_member(workspace_id: str, member_id: str, body: WorkspaceMemberUpdate,
                  request: Request, type: Literal["user", "org"], user=Depends(current_user)):
    dao = request.app.state.dao
    _managed_workspace(dao, workspace_id, user)
    if type == "org" and body.role == "admin":
        raise HTTPException(status_code=422, detail="Organizations cannot be workspace administrators")
    update = dao.update_workspace_org if type == "org" else dao.update_workspace_member
    try:
        member = update(workspace_id, member_id, role=body.role)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"member": member}


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(workspace_id: str, member_id: str, request: Request, type: Literal["user", "org"], user=Depends(current_user)):
    dao = request.app.state.dao
    _managed_workspace(dao, workspace_id, user)
    delete = dao.delete_workspace_org if type == "org" else dao.delete_workspace_member
    try:
        deleted = delete(workspace_id, member_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Member not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
