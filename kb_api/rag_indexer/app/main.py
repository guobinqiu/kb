import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from kb_api.rag_indexer.common.api_errors import upstream_exception_handler, unhandled_exception_handler

from kb_api.rag_indexer.common.config import AppConfig
from kb_api.rag_indexer.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient
from kb_api.rag_indexer.core.api.routes import register_routes
from kb_api.rag_indexer.core.api.index_errors import install_index_error_handlers
from kb_api.rag_indexer.core.loader import load_app_config
from kb_api.rag_indexer.common.tracing import install_request_id_middleware
from kb_api.rag_indexer.common.upstream import UpstreamServiceError


logger = logging.getLogger("rag_indexer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_app(app, load_app_config())
    logger.info("Starting RAG API ...", extra={"event": "startup_start"})
    index_worker = _start_index_worker(app)
    logger.info("RAG API startup done", extra={"event": "startup_ready"})
    try:
        yield
    finally:
        if index_worker is not None:
            index_worker.stop()
        _close_clients(app)
        logger.info("RAG API closed", extra={"event": "shutdown"})


app = FastAPI(title="Brain RAG API", lifespan=lifespan)
install_request_id_middleware(app, service_name="rag_indexer")
install_index_error_handlers(app)


app.add_exception_handler(UpstreamServiceError, upstream_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_routes(app)


@app.get("/health")
def health():
    return {"status": "ok"}


def _configure_app(app: FastAPI, config: AppConfig) -> None:
    if config.services.vector is None:
        raise ValueError("rag vector service is required")

    parser = _build_parser_client()
    inference = _build_inference_client()
    try:
        parser.start()
    except Exception:
        parser.close()
        inference.close()
        raise

    vector_backend = config.services.vector.provider
    if vector_backend == "qdrant":
        vector = QdrantVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            url=config.services.vector.base_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            quantization=config.services.vector.quantization,
            api_key=config.services.vector.api_key,
            retry=config.services.vector.retry,
        )
    elif vector_backend == "milvus":
        vector = MilvusVectorClient(
            dense=inference.dense,
            sparse=inference.sparse,
            uri=config.services.vector.base_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            token=config.services.vector.token,
            retry=config.services.vector.retry,
        )
    else:
        raise ValueError(f"unsupported vector: {config.services.vector.provider}")

    app.state.config = config
    app.state.config_name = config.name
    app.state.parser_client = parser
    app.state.inference_client = inference
    app.state.vector_client = vector
    app.state.ready = True


def _build_parser_client():
    from kb_api.rag_indexer.parser.config_loader import load_parser_config
    from kb_api.rag_indexer.parser.client import LocalParserClient
    from kb_api.rag_indexer.parser.service import ParserService

    return LocalParserClient(ParserService(load_parser_config()))


def _build_inference_client():
    from kb_api.rag_indexer.inference.service import load_inference_components

    return load_inference_components()


def _start_index_worker(app: FastAPI):
    rabbitmq_url = os.getenv("RABBITMQ_URL", "").strip()
    if not rabbitmq_url:
        return None
    from kb_api.rag_indexer.rabbitmq import RabbitIndexWorker

    worker = RabbitIndexWorker(
        app.state,
        rabbitmq_url,
        task_queue=os.getenv("INDEX_TASK_QUEUE", "kb.index.tasks"),
        callback_url=os.getenv("INDEX_RESULT_CALLBACK_URL", "http://kb_api:6100/api/v1/index-results"),
        callback_timeout=float(os.getenv("INDEX_RESULT_CALLBACK_TIMEOUT", "10")),
    )
    worker.start()
    return worker


def _close_clients(app: FastAPI) -> None:
    state = app.state
    for name in ("parser_client", "vector_client", "inference_client"):
        component = getattr(state, name, None)
        if component is None:
            continue
        close = getattr(component, "close", None)
        if callable(close):
            close()
            continue
        stop = getattr(component, "stop", None)
        if callable(stop):
            stop()
    state.ready = False
