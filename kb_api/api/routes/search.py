from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from kb_api.api.schemas import SearchRequest
from kb_api.auth import resolve_principal
from kb_api.permissions import WORKSPACE_SEARCH, has_workspace_permission
from kb_api.rag_retriever.schemas import SearchRequest as RetrieverSearchRequest
from kb_api.rate_limit import require_rate_limit

router = APIRouter(tags=["search"], dependencies=[Depends(require_rate_limit)])


def _search(request: Request, body: SearchRequest, *, app_id: str | None = None, principal: dict | None = None):
    principal = principal or resolve_principal(request)
    repository = request.app.state.repository
    app_id = app_id or request.headers.get("X-App-Id") or principal.get("app_id")
    if not app_id:
        raise HTTPException(status_code=400, detail="X-App-Id is required")
    app = repository.get_app_by_business_id(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if principal["principal_type"] == "api_key":
        if principal["app_id"] != app_id:
            raise HTTPException(status_code=403, detail="App is outside visible scope")
        accessible = {item["id"] for item in repository.list_workspaces(app["id"])}
    else:
        org = repository.get_org(principal["org_id"]) if principal.get("org_id") else None
        if principal["user"]["role"] != "owner" and (not org or org["app_id"] != app["id"]):
            raise HTTPException(status_code=403, detail="App is outside visible scope")
        accessible = {
            item["id"] for item in repository.list_workspaces(app["id"])
            if has_workspace_permission(repository, principal["user"], item, WORKSPACE_SEARCH)
        }
    requested = body.workspace_ids
    if requested is not None:
        if not set(requested) <= accessible:
            raise HTTPException(status_code=403, detail="Workspace is outside visible scope")
        workspace_ids = sorted(set(requested))
    else:
        workspace_ids = sorted(accessible)
    if not workspace_ids:
        return {"results": []}
    payload = body.model_dump(exclude={"workspace_ids"}, exclude_none=True) | {
        "app_id": app_id,
        "workspace_ids": workspace_ids,
    }
    return request.app.state.retriever.search(RetrieverSearchRequest.model_validate(payload))


@router.post("/api/v1/rag/search")
def search(body: SearchRequest, request: Request):
    return JSONResponse(status_code=200, content=_search(request, body))


@router.get("/api/v1/rag/config")
def search_config(request: Request):
    resolve_principal(request)
    retriever = request.app.state.retriever
    config = retriever.search_config
    return {
        "mode": config.mode,
        "top_k": config.top_k,
        "rerank": config.rerank and retriever.inference.rerank is not None,
        "rerank_fetch_k": config.rerank_fetch_k,
        "capabilities": {"sparse_vector": retriever.vector.supports_sparse_vector()},
    }
