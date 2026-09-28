import json
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from kb_api.rag_indexer.core.auth import Principal
from kb_api.rag_indexer.core.auth import validate_app_id


def require_ready(state):
    if not state.ready:
        raise HTTPException(503, "search is not initialized")


def component_config(component: Any) -> dict[str, Any] | None:
    if component is None:
        return None
    data = {
        "name": getattr(component, "name", None),
        "model_name": getattr(component, "model_name", None),
        "url": getattr(component, "url", None),
        "timeout": getattr(component, "timeout", None),
    }
    return {key: value for key, value in data.items() if value is not None}


def required_component_status(component: Any, *, error: str | None = None) -> str:
    if error:
        return "error"
    return "ready" if is_ready(component) else "error"


def component_model(component_config: Any) -> str | None:
    if component_config is None:
        return None
    return getattr(component_config, "model_name", None) or getattr(component_config, "name", None)


def is_ready(component: Any) -> bool:
    ping = getattr(component, "ping", None)
    if callable(ping):
        return bool(ping())
    return bool(getattr(component, "ready", False))


def vector_scope(state, principal: Principal):
    principal = effective_principal(principal)
    if not principal.app_id:
        return nullcontext()
    context = getattr(state.vector_client, "app_scope", None)
    if callable(context):
        return context(principal.app_id)
    return nullcontext()


def effective_principal(principal) -> Principal:
    if isinstance(principal, Principal):
        return principal
    return Principal(type="admin", app_id="")


def app_principal(principal: Principal, app_id: str | None) -> Principal:
    principal = effective_principal(principal)
    if principal.type == "admin":
        selected_app_id = app_id or principal.app_id
        if not selected_app_id:
            raise HTTPException(status_code=400, detail="app_id is required")
        validate_app_id(selected_app_id)
        return Principal(type="admin", app_id=selected_app_id)
    if app_id and app_id != principal.app_id:
        raise HTTPException(status_code=403, detail="app_id is not allowed")
    return principal


def scoped_vector(state, principal: Principal):
    scoped_methods = {
        "delete_file_chunks",
        "encode_dense_query",
        "encode_sparse_query",
        "get_total_chunks",
        "list_chunks",
        "query_dense_vector",
        "query_sparse_vector",
        "search_dense",
        "search_sparse",
    }

    class ScopedVector:
        def __getattr__(self, name):
            attr = getattr(state.vector_client, name)
            if not callable(attr) or name not in scoped_methods:
                return attr

            def call(*args, **kwargs):
                if not app_collection_exists(state, principal):
                    return 0 if name in {"delete_file_chunks", "get_total_chunks"} else []
                with vector_scope(state, principal):
                    return attr(*args, **kwargs)

            return call

    return ScopedVector()


def require_app_collection(state, principal: Principal) -> None:
    principal = effective_principal(principal)
    if principal.app_id and not app_collection_exists(state, principal):
        raise HTTPException(status_code=409, detail="app collection is not initialized")


def app_collection_status(state, app_id: str) -> dict[str, Any]:
    try:
        validate_app_id(app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    principal = Principal(type="admin", app_id=app_id)
    exists = app_collection_exists(state, principal)
    chunk_count = scoped_vector(state, principal).get_total_chunks(None) if exists else 0
    return {
        "app_id": app_id,
        "exists": exists,
        "chunk_count": chunk_count,
        "empty": chunk_count == 0,
    }


def app_collection_exists(state, principal: Principal) -> bool:
    principal = effective_principal(principal)
    if not principal.app_id:
        return True
    return state.vector_client.app_collection_exists(principal.app_id)


def iso_datetime(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sse_data(value: Any) -> str:
    return f"data: {json.dumps(value, ensure_ascii=False)}\n\n"
