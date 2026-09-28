from fastapi import HTTPException, Request

from kb_api.rag_indexer.core.auth import Principal


def require_principal(request: Request) -> Principal:
    principal_type = request.headers.get("X-Principal-Type")
    app_id = request.headers.get("X-App-Id")
    if principal_type in {"user", "api_key"} and app_id:
        return Principal(type="app", app_id=app_id)
    raise HTTPException(401, "trusted gateway identity is required")
