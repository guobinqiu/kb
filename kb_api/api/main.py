from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kb_api.api.auth import hash_password
from kb_api.api.config import Settings, load_api_limits
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
from kb_api.rag_retriever.service import load_retriever
from kb_api.rag_retriever.common.upstream import UpstreamServiceError
from kb_api.api.services.minio import MinioStorage
from kb_api.api.telemetry import flush_telemetry, get_trace_id, install_search_tracing


logger = logging.getLogger("kb_api")


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
    dao=None,
    storage=None,
    queue=None,
    retriever=None,
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
            if managed_retriever is not None:
                managed_retriever.close()
            storage.close()
            dao.close()
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
    application.state.dao = dao
    application.state.storage = storage
    application.state.queue = queue
    application.state.token_secret = token_secret or config.token_secret
    application.state.token_ttl_seconds = config.token_ttl_seconds
    application.state.api_limits = load_api_limits()
    if provided_retriever is not None:
        application.state.retriever = provided_retriever
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
    return application


app = create_app()
