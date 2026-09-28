from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kb_api.auth import create_token, hash_password, resolve_principal, verify_password
from kb_api.config import Settings, load_api_limits
from kb_api.index_results import apply_index_result
from kb_api.queue import RabbitMQClient
from kb_api.repository import PostgresRepository
from kb_api.api.routes.apps import router as apps_router
from kb_api.api.routes.chunks import router as chunks_router
from kb_api.api.routes.files import router as files_router
from kb_api.api.routes.orgs import router as orgs_router
from kb_api.api.routes.search import router as search_router
from kb_api.api.routes.users import router as users_router
from kb_api.api.routes.workspaces import apps_router as workspace_apps_router, router as workspaces_router
from kb_api.rag_retriever.service import load_retriever
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.api.schemas import LoginRequest, PasswordChange
from kb_api.storage import MinioStorage
from kb_api.telemetry import flush_telemetry, get_trace_id, install_search_tracing


logger = logging.getLogger("kb_api")


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


def _error_detail(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "\n".join(item.get("msg", str(item)) if isinstance(item, dict) else str(item) for item in detail)
    return str(detail)


def _error_response(status_code: int, error: str, *, retryable: bool = False, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers, content={
        "success": False, "error": error, "service": "kb_api",
        "retryable": retryable, "traceId": get_trace_id(),
    })


async def _http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(
        exc.status_code,
        _error_detail(exc.detail),
        retryable=exc.status_code == 503,
        headers=exc.headers,
    )


async def _validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(422, _error_detail(exc.errors()), retryable=False)


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or get_trace_id()
    request.state.trace_id = trace_id
    headers = {"X-Trace-Id": trace_id}
    traceparent = getattr(request.state, "traceparent", None)
    if traceparent:
        headers["traceparent"] = traceparent
    logger.error(
        "Unhandled KB API error",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"trace_id": trace_id, "method": request.method, "path": request.url.path},
    )
    return JSONResponse(status_code=500, headers=headers, content={
        "success": False, "error": str(exc) or repr(exc), "service": "kb_api",
        "retryable": False, "traceId": trace_id,
    })


def create_app(
    *,
    repository=None,
    storage=None,
    queue=None,
    retriever=None,
    vector=None,
    settings: Settings | None = None,
    token_secret: str | None = None,
    initialize: bool = True,
) -> FastAPI:
    config = settings or Settings.from_env()
    repository = repository or PostgresRepository(config.database_url)
    storage = storage or MinioStorage(
        config.minio_endpoint,
        config.minio_access_key,
        config.minio_secret_key,
        config.minio_bucket,
        config.minio_secure,
        config.minio_public_url,
    )
    queue = queue or RabbitMQClient(config.rabbitmq_url)
    managed_retriever = None
    provided_retriever = retriever
    provided_vector = vector

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal managed_retriever
        if provided_retriever is None:
            managed_retriever = load_retriever()
            application.state.retriever = managed_retriever
            application.state.vector = managed_retriever.vector
        if initialize:
            initialize_storage = getattr(storage, "initialize", None)
            if callable(initialize_storage):
                initialize_storage()
            if not repository.get_user_by_name(config.admin_name):
                repository.create_user(
                    org_id=None,
                    name=config.admin_name,
                    password_hash=hash_password(config.admin_password),
                    role="owner",
                )
        try:
            yield
        finally:
            queue.close()
            if managed_retriever is not None:
                managed_retriever.close()
            storage.close()
            repository.close()
            flush_telemetry()

    application = FastAPI(title="KB API", version="0.1.0", lifespan=lifespan)
    install_search_tracing(application, service_name="kb_api")
    application.add_exception_handler(
        UpstreamServiceError,
        lambda _request, exc: JSONResponse(status_code=exc.status_code, content=exc.detail()),
    )
    application.add_exception_handler(HTTPException, _http_exception)
    application.add_exception_handler(RequestValidationError, _validation_exception)
    application.add_exception_handler(Exception, _unhandled_exception)
    application.state.repository = repository
    application.state.storage = storage
    application.state.queue = queue
    application.state.token_secret = token_secret or config.token_secret
    application.state.token_ttl_seconds = config.token_ttl_seconds
    application.state.api_limits = load_api_limits()
    if provided_retriever is not None:
        application.state.retriever = provided_retriever
    if provided_vector is not None:
        application.state.vector = provided_vector

    @application.get("/health")
    def health():
        return {"status": "ok", "service": "kb_api"}

    @application.post("/api/v1/auth/login")
    def login(body: LoginRequest, request: Request):
        user = repository.get_user_by_name(body.name)
        if not user or not verify_password(body.password, user.get("password_hash")):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if user.get("deleted_at") or (
            user["role"] != "owner" and (
                not user.get("org_id") or not repository.is_active_org(user["org_id"])
            )
        ):
            raise HTTPException(status_code=401, detail="Account disabled")
        token = create_token(
            {"sub": user["id"]},
            request.app.state.token_secret,
            expires_in=timedelta(seconds=request.app.state.token_ttl_seconds),
        )
        return {"access_token": token, "user": _public_user(user)}

    @application.get("/api/v1/auth/me")
    def me(request: Request):
        principal = resolve_principal(request)
        if principal["principal_type"] != "user":
            raise HTTPException(status_code=403, detail="User token required")
        return _public_user(principal["user"]) | {
            "is_platform_admin": principal["user"]["role"] == "owner",
        }

    @application.patch("/api/v1/auth/password")
    def change_password(body: PasswordChange, request: Request):
        principal = resolve_principal(request)
        if principal["principal_type"] != "user":
            raise HTTPException(status_code=403, detail="User token required")
        user = principal["user"]
        if not verify_password(body.old_password, user.get("password_hash")):
            raise HTTPException(status_code=403, detail="Invalid current password")
        repository.update_user(user["id"], password_hash=hash_password(body.new_password))
        return {"success": True}

    @application.post("/api/v1/index-results", status_code=204)
    def update_index_result(body: dict, request: Request):
        apply_index_result(request.app.state.repository, request.app.state.storage, body)
        return Response(status_code=204)

    @application.get("/api/v1/auth/verify")
    def verify(request: Request, response: Response):
        principal = resolve_principal(request)
        requested_app_id = request.headers.get("X-App-Id")
        if requested_app_id:
            if principal["principal_type"] == "api_key":
                allowed = principal["app_id"] == requested_app_id
            else:
                allowed = any(
                    app["app_id"] == requested_app_id
                    for app in repository.list_apps(
                        None if principal["user"]["role"] == "owner" else principal["org_id"]
                    )
                )
            if not allowed:
                raise HTTPException(status_code=403, detail="App is outside visible scope")
            principal["app_id"] = requested_app_id
        requested_org_id = request.headers.get("X-Org-Id")
        if requested_org_id:
            org = repository.get_org(requested_org_id)
            app = repository.get_app(org["app_id"]) if org and repository.is_active_org(requested_org_id) else None
            if not app or (principal.get("app_id") and app["app_id"] != principal["app_id"]):
                raise HTTPException(status_code=403, detail="Org is outside visible scope")
            if principal["principal_type"] == "user" and principal["user"]["role"] != "owner":
                if requested_org_id not in repository.subtree_org_ids(principal["org_id"]):
                    raise HTTPException(status_code=403, detail="Org is outside visible scope")
            principal["app_id"] = app["app_id"]
            principal["org_id"] = requested_org_id
        requested_workspace_id = request.headers.get("X-Workspace-Id")
        if requested_workspace_id:
            workspace = repository.get_workspace(requested_workspace_id)
            app = repository.get_app(workspace["app_id"]) if workspace else None
            if not app or app["app_id"] != principal.get("app_id"):
                raise HTTPException(status_code=403, detail="Workspace is outside visible scope")
            if principal["principal_type"] == "user" and not repository.has_workspace_access(principal["user"], requested_workspace_id):
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

    application.include_router(apps_router)
    application.include_router(chunks_router)
    application.include_router(orgs_router)
    application.include_router(users_router)
    application.include_router(workspace_apps_router)
    application.include_router(workspaces_router)
    application.include_router(files_router)
    application.include_router(search_router)
    return application


app = create_app()
