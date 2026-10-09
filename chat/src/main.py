from contextlib import AsyncExitStack, asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from openai import APIConnectionError, APIStatusError, RateLimitError  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException
from chat.src.agent.graphs.chat import build_chat_graph  # noqa: E402
from chat.src.agent.nodes.llm import init_semaphore  # noqa: E402
from chat.src.agent.registry import register_graph, set_checkpointer  # noqa: E402
from chat.src.api.auth import AuthenticationMiddleware  # noqa: E402
from chat.src.api.errors import unhandled_exception_handler  # noqa: E402
from chat.src.api.middleware import add_trace_id_and_timeout, limiter  # noqa: E402
from chat.src.api.routes import chat as chat_routes  # noqa: E402
from chat.src.api.routes import health as health_routes  # noqa: E402
from chat.src.api.routes import threads as thread_routes  # noqa: E402
from chat.src.config import settings  # noqa: E402
from chat.src.infra.tracing import get_trace_id  # noqa: E402
from chat.src.rag.client import get_rag_client  # noqa: E402

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_semaphore(settings.llm_concurrency_limit)

    # RAG client 单例：构造真实 HTTP 客户端
    rag = get_rag_client()
    rag_client_for_lifespan = rag
    checkpointer_cm = None

    try:
        checkpointer_cm, checkpointer, auth_pool = await _create_checkpointer()
        app.state.auth_pool = auth_pool
        set_checkpointer(checkpointer)

        # 注册 chat graph（pre-fetch 架构，无需 llm_with_tools）
        register_graph("chat", build_chat_graph(checkpointer))

        yield
    finally:
        if checkpointer_cm is not None:
            await checkpointer_cm.__aexit__(None, None, None)
        try:
            await rag_client_for_lifespan.aclose()
        except Exception:
            # lifespan 关闭阶段失败不应抛错阻断 shutdown
            pass


async def _create_checkpointer():
    resources = AsyncExitStack()
    try:
        pool = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=5,
            open=False,
            timeout=settings.request_timeout,
            check=AsyncConnectionPool.check_connection,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await resources.enter_async_context(pool)
        await pool.wait(timeout=settings.request_timeout)
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
    except Exception:
        await resources.aclose()
        return AsyncExitStack(), MemorySaver(), None
    return resources, checkpointer, pool


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.state.service_name = "chat"
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthenticationMiddleware)
app.middleware("http")(add_trace_id_and_timeout)


# ─────────────────────────────────────
# 异常处理
# ─────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": str(exc.detail), "service": "chat", "traceId": get_trace_id()},
        headers={
            "Retry-After": str(exc.detail),
            "X-Trace-Id": get_trace_id(),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": e["loc"][-1], "msg": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": str(exc), "service": "chat", "details": errors, "traceId": get_trace_id()}
    )


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError):
    return JSONResponse(status_code=429, content={"error": str(exc), "service": "chat", "traceId": get_trace_id()})


@app.exception_handler(APIStatusError)
async def api_status_handler(request: Request, exc: APIStatusError):
    return JSONResponse(status_code=502, content={"error": str(exc), "service": "chat", "traceId": get_trace_id()})


@app.exception_handler(APIConnectionError)
async def connection_handler(request: Request, exc: APIConnectionError):
    return JSONResponse(status_code=503, content={"error": str(exc), "service": "chat", "traceId": get_trace_id()})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "service": "chat", "traceId": get_trace_id()},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def general_handler(request: Request, exc: Exception):
    return await unhandled_exception_handler(request, exc)


# ─────────────────────────────────────
# 路由注册
# ─────────────────────────────────────
app.include_router(chat_routes.router)
app.include_router(health_routes.router)
app.include_router(thread_routes.router)
