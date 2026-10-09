import logging
import os
import signal
from types import SimpleNamespace

from kb_api.rag_indexer.common.config import AppConfig
from kb_api.rag_indexer.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_indexer.clients.vector.postgres import PostgresVectorClient
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient
from kb_api.rag_indexer.core.loader import load_app_config
from kb_api.rag_indexer.parser.config_loader import load_parser_config
from kb_api.rag_indexer.parser.client import LocalParserClient
from kb_api.rag_indexer.parser.service import ParserService
from kb_api.rag_indexer.inference.service import load_inference_components
from kb_api.rag_indexer.rabbitmq import RabbitIndexWorker
from kb_api.logging_config import configure_logging


logger = logging.getLogger("rag_indexer")


def main() -> None:
    configure_logging()
    rabbitmq_url = os.getenv("RABBITMQ_URL", "").strip()
    if not rabbitmq_url:
        raise ValueError("RABBITMQ_URL is required")
    config = load_app_config()
    state = _build_state(config)
    try:
        worker = RabbitIndexWorker(
            state,
            rabbitmq_url,
            task_queue=os.getenv("INDEX_TASK_QUEUE", "kb.index.tasks"),
            callback_url=config.indexer.callback.url,
            callback_timeout=config.indexer.callback.timeout,
        )

        def stop(_signum, _frame):
            worker.stop()

        previous_handlers = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
        try:
            for name in previous_handlers:
                signal.signal(name, stop)
            logger.info("Starting RAG Indexer", extra={"event": "startup_ready"})
            worker.run()
        finally:
            for name, handler in previous_handlers.items():
                signal.signal(name, handler)
    finally:
        _close_clients(state)
        logger.info("RAG Indexer closed", extra={"event": "shutdown"})


def _build_state(config: AppConfig):
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
            bm25=config.services.vector.bm25,
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
            bm25=config.services.vector.bm25,
            uri=config.services.vector.base_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            token=config.services.vector.token,
            retry=config.services.vector.retry,
        )
    elif vector_backend == "postgres":
        vector = PostgresVectorClient(
            dense=inference.dense,
            bm25=config.services.vector.bm25,
            database_url=config.services.vector.database_url,
            timeout=config.services.vector.timeout,
            query_timeout=config.services.vector.query_timeout,
            write_timeout=config.services.vector.write_timeout,
            init_timeout=config.services.vector.init_timeout,
            drop_timeout=config.services.vector.drop_timeout,
            retry=config.services.vector.retry,
        )
        vector.start()
    else:
        raise ValueError(f"unsupported vector: {config.services.vector.provider}")

    return SimpleNamespace(
        config=config, parser_client=parser, inference_client=inference, vector_client=vector,
    )


def _build_parser_client():
    return LocalParserClient(ParserService(load_parser_config()))


def _build_inference_client():
    return load_inference_components()


def _close_clients(state) -> None:
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


if __name__ == "__main__":
    main()
