from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from kb_api.rag_indexer.core.api.schemas import FileIndexRequest, PresignRequest
from kb_api.rag_indexer.core.api.services import files as service
from kb_api.rag_indexer.core.api.services.auth import require_principal


router = APIRouter()


@router.post("/api/v1/rag/files")
def index_file(request: Request, req: FileIndexRequest, principal=Depends(require_principal)):
    try:
        return service.index_file(request.app.state, req, principal)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)


@router.post("/api/v1/rag/presign")
def presign_object(request: Request, req: PresignRequest, principal=Depends(require_principal)):
    return service.client_presign_object(request.app.state, req, principal)


@router.get("/api/v1/rag/apps/{app_id}/chunks/{chunk_id}/dense-vector")
def dense_vector(request: Request, app_id: str, chunk_id: str, principal=Depends(require_principal)):
    return service.dense_vector(request.app.state, app_id, chunk_id, principal)


@router.delete("/api/v1/rag/files/{file_id}")
def delete_file(request: Request, file_id: str, principal=Depends(require_principal)):
    return service.client_delete_file(request.app.state, file_id, principal)
