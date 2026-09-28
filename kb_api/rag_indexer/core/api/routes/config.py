from fastapi import APIRouter, Depends, Request

from kb_api.rag_indexer.core.api.services.auth import require_principal
from kb_api.rag_indexer.core.api.services import config as service


router = APIRouter()


@router.get("/api/v1/rag/config")
def open_config(request: Request, principal=Depends(require_principal)):
    return service.get_config(request.app.state, principal)
