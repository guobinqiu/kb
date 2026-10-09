from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from kb_api.api.auth import hash_password
from kb_api.api.config import Settings, load_api_limits
from kb_api.api.middleware import AuthenticationMiddleware
from kb_api.api.services.rabbitmq import RabbitMQClient
from kb_api.api.dao import PostgresDAO
from kb_api.api.routes.apps import router as apps_router
from kb_api.api.routes.auth import router as auth_router
from kb_api.api.routes.chunks import router as chunks_router
from kb_api.api.routes.files import router as files_router
from kb_api.api.routes.health import router as health_router
from kb_api.api.routes.orgs import router as orgs_router
from kb_api.api.routes.search import router as search_router
from kb_api.api.routes.users import router as users_router
from kb_api.api.routes.workspaces import apps_router as workspace_apps_router, router as workspaces_router
from kb_api.rag_search.service import load_search_service
from kb_api.rag_search.common.upstream import UpstreamServiceError
from kb_api.api.services.minio import MinioStorage
from kb_api.api.telemetry import flush_telemetry, get_trace_id, install_search_tracing
from kb_api.logging_config import configure_logging, log_request_error


logger = logging.getLogger("kb_api")


def _install_openapi(application: FastAPI) -> None:
    def openapi():
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = get_openapi(title=application.title, version=application.version, routes=application.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "AppId": {"type": "apiKey", "in": "header", "name": "X-App-Id"},
            "AppApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        }
        public = {("/health", "get"), ("/api/v1/auth/login", "post")}
        app_access = {
            ("/api/v1/rag/search", "post"),
            ("/api/v1/rag/config", "get"),
        }
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if (path, method) in public:
                    operation["security"] = []
                elif path == "/api/v1/index-results":
                    operation["security"] = []
                elif (path, method) in app_access:
                    operation["security"] = [
                        {"BearerAuth": [], "AppId": []},
                        {"AppApiKey": [], "AppId": []},
                    ]
                else:
                    operation["security"] = [{"BearerAuth": []}]
        application.openapi_schema = schema
        return schema

    application.openapi = openapi


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


def _log_request_error(request: Request, status_code: int, error: str, *, level: int) -> None:
    trace_id = getattr(request.state, "trace_id", None) or get_trace_id()
    log_request_error(
        logger,
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        trace_id=trace_id,
        error=error,
        level=level,
    )


async def _http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    error = _error_detail(exc.detail)
    if exc.status_code >= 500:
        level = logging.ERROR
    elif exc.status_code in {403, 409}:
        level = logging.WARNING
    else:
        level = logging.DEBUG
    _log_request_error(request, exc.status_code, error, level=level)
    return _error_response(
        exc.status_code,
        error,
        retryable=exc.status_code == 503,
        headers=exc.headers,
    )


async def _validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:
    error = _error_detail(exc.errors())
    _log_request_error(request, 422, error, level=logging.DEBUG)
    return _error_response(422, error, retryable=False)


async def _upstream_exception(request: Request, exc: UpstreamServiceError) -> JSONResponse:
    _log_request_error(request, exc.status_code, exc.error or str(exc), level=logging.ERROR)
    return JSONResponse(status_code=exc.status_code, content=exc.detail())


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
    dao=None,
    storage=None,
    queue=None,
    search_service=None,
    vector=None,
    settings: Settings | None = None,
    token_secret: str | None = None,
    initialize: bool = True,
) -> FastAPI:
    config = settings or Settings.from_env()
    dao = dao or PostgresDAO(config.database_url)
    storage = storage or MinioStorage(
        config.minio_endpoint,
        config.minio_access_key,
        config.minio_secret_key,
        config.minio_bucket,
        config.minio_secure,
        config.minio_public_url,
    )
    queue = queue or RabbitMQClient(config.rabbitmq_url)
    managed_search_service = None
    provided_search_service = search_service
    provided_vector = vector

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal managed_search_service
        if provided_search_service is None:
            managed_search_service = load_search_service()
            application.state.search_service = managed_search_service
            application.state.vector = managed_search_service.vector
        if initialize:
            initialize_storage = getattr(storage, "initialize", None)
            if callable(initialize_storage):
                initialize_storage()
            if not dao.get_user_by_name(config.admin_name):
                dao.create_user(
                    org_id=None,
                    name=config.admin_name,
                    password_hash=hash_password(config.admin_password),
                    role="owner",
                )
        try:
            yield
        finally:
            queue.close()
            if managed_search_service is not None:
                managed_search_service.close()
            storage.close()
            dao.close()
            flush_telemetry()

    configure_logging()
    application = FastAPI(title="KB API", version="0.1.0", lifespan=lifespan)
    install_search_tracing(application, service_name="kb_api")
    application.add_middleware(AuthenticationMiddleware)
    application.add_exception_handler(UpstreamServiceError, _upstream_exception)
    application.add_exception_handler(HTTPException, _http_exception)
    application.add_exception_handler(RequestValidationError, _validation_exception)
    application.add_exception_handler(Exception, _unhandled_exception)
    application.state.dao = dao
    application.state.storage = storage
    application.state.queue = queue
    application.state.token_secret = token_secret or config.token_secret
    application.state.token_ttl_seconds = config.token_ttl_seconds
    application.state.api_limits = load_api_limits()
    if provided_search_service is not None:
        application.state.search_service = provided_search_service
    if provided_vector is not None:
        application.state.vector = provided_vector

    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(apps_router)
    application.include_router(chunks_router)
    application.include_router(orgs_router)
    application.include_router(users_router)
    application.include_router(workspace_apps_router)
    application.include_router(workspaces_router)
    application.include_router(files_router)
    application.include_router(search_router)
    _install_openapi(application)
    return application


app = create_app()
