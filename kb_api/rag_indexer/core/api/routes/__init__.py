from fastapi import FastAPI

from kb_api.rag_indexer.core.api.routes.config import router as config_router
from kb_api.rag_indexer.core.api.routes.health import router as health_router
from kb_api.rag_indexer.core.api.routes.files import router as files_router


def register_routes(app: FastAPI) -> None:
    for router in (
        health_router,
        config_router,
        files_router,
    ):
        app.router.routes.extend(router.routes)
