from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.auth import current_user
from kb_api.api.schemas import AppCreate, AppUpdate


router = APIRouter(prefix="/api/v1/apps", tags=["apps"])


def _require_owner(user: dict) -> None:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Platform administrator required")


def _can_access_app(repository, user: dict, app_id: str) -> bool:
    if user["role"] == "owner":
        return repository.get_app(app_id) is not None
    return any(app["id"] == app_id for app in repository.list_apps(user["org_id"]))


def _visible_app(repository, user: dict, app: dict) -> dict:
    if user["role"] == "owner":
        return app
    return {key: value for key, value in app.items() if key != "api_key"}


def _vector(request: Request):
    return getattr(request.app.state, "vector", None)


@router.get("")
def list_apps(request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    apps = repository.list_apps(None if user["role"] == "owner" else user["org_id"], include_disabled=user["role"] == "owner")
    return {"apps": [_visible_app(repository, user, app) for app in apps]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_app(body: AppCreate, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    _require_owner(user)
    if repository.get_app_by_business_id(body.app_id):
        raise HTTPException(status_code=409, detail="app_id already exists")
    app, org = repository.create_app(body.name, body.app_id)
    vector = _vector(request)
    if vector is not None:
        try:
            vector.ensure_app_collection(app["app_id"])
        except Exception:
            repository.delete_app(app["id"])
            raise
    return {"app": app, "org": org}


@router.get("/{app_id}")
def get_app(app_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    if not _can_access_app(repository, user, app_id):
        raise HTTPException(status_code=404, detail="App not found")
    return _visible_app(repository, user, repository.get_app(app_id))


@router.put("/{app_id}")
def update_app(app_id: str, body: AppUpdate, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    _require_owner(user)
    app = repository.update_app(app_id, body.name)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return app


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_app(app_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    _require_owner(user)
    app = repository.get_app(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if repository.list_workspaces(app_id):
        raise HTTPException(status_code=409, detail="App contains workspaces")
    vector = _vector(request)
    if vector is not None:
        vector.drop_app_collection(app["app_id"])
    if not repository.delete_app(app_id):
        raise HTTPException(status_code=404, detail="App not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
