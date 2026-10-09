from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.api.auth import current_user
from kb_api.api.schemas import AppCreate, AppUpdate


router = APIRouter(prefix="/api/v1/apps", tags=["apps"])


def _require_owner(user: dict) -> None:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Platform administrator required")


def _can_access_app(dao, user: dict, app_id: str) -> bool:
    if user["role"] == "owner":
        return dao.get_app_by_business_id(app_id) is not None
    return any(app["app_id"] == app_id for app in dao.list_apps(user["org_id"]))


def _visible_app(dao, user: dict, app: dict) -> dict:
    if user["role"] == "owner":
        return app
    return {key: value for key, value in app.items() if key != "api_key"}


def _vector(request: Request):
    return getattr(request.app.state, "vector", None)


@router.get("")
def list_apps(request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    apps = dao.list_apps(None if user["role"] == "owner" else user["org_id"])
    return {"apps": [_visible_app(dao, user, app) for app in apps]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_app(body: AppCreate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    _require_owner(user)
    if dao.get_app_by_business_id(body.app_id):
        raise HTTPException(status_code=409, detail="app_id already exists")
    vector = _vector(request)
    with dao._connect() as connection:
        app, org = dao.create_app(body.name, body.app_id, connection=connection)
        if vector is not None:
            vector.ensure_app_collection(app["app_id"])
    return {"app": app, "org": org}


@router.get("/{app_id}")
def get_app(app_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    if not _can_access_app(dao, user, app_id):
        raise HTTPException(status_code=404, detail="App not found")
    return _visible_app(dao, user, dao.get_app_by_business_id(app_id))


@router.patch("/{app_id}")
def update_app(app_id: str, body: AppUpdate, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    _require_owner(user)
    existing = dao.get_app_by_business_id(app_id)
    app = dao.update_app(existing["id"], body.name) if existing else None
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return app


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_app(app_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    _require_owner(user)
    app = dao.get_app_by_business_id(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if dao.list_workspaces(app["id"]):
        raise HTTPException(status_code=409, detail="App contains workspaces")
    if dao.has_app_orgs(app["id"]):
        raise HTTPException(status_code=409, detail="App contains orgs")
    vector = _vector(request)
    if vector is not None:
        vector.drop_app_collection(app["app_id"])
    try:
        deleted = dao.delete_app(app["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="App not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
