from fastapi import APIRouter, Depends, Request

from kb_api.rag_indexer.core.api.services import health as service


router = APIRouter()


@router.get("/ready")
def ready(request: Request):
    return service.ready(request.app.state)
