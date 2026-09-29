from fastapi import APIRouter, Depends, HTTPException, Query, Request

from kb_api.api.auth import current_user
from kb_api.api.permissions import WORKSPACE_FILES_READ, has_workspace_permission


router = APIRouter(prefix="/api/v1/workspaces", tags=["chunks"])


@router.get("/{workspace_id}/chunks")
def list_chunks(
    workspace_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    file_ids: list[str] | None = Query(default=None, max_length=1000),
    user=Depends(current_user),
):
    dao = request.app.state.dao
    workspace = dao.get_workspace(workspace_id)
    if not workspace or not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_READ):
        raise HTTPException(status_code=404, detail="Workspace not found")
    app = dao.get_app(workspace["app_id"])
    if app is None:
        raise HTTPException(status_code=404, detail="App not found")
    visible_files = {
        record["id"]: record
        for record in dao.list_workspace_files(workspace_id)
    }
    allowed_file_ids = list(visible_files)
    if file_ids is not None:
        requested_file_ids = set(file_ids)
        allowed_file_ids = [file_id for file_id in allowed_file_ids if file_id in requested_file_ids]
    if not allowed_file_ids:
        return {"chunks": [], "next_cursor": None, "has_more": False}

    vector = getattr(request.app.state.retriever, "vector", None)
    if vector is None:
        raise HTTPException(status_code=503, detail="Vector database is unavailable")
    if not vector.app_collection_exists(app["app_id"]):
        return {"chunks": [], "next_cursor": None, "has_more": False}

    with vector.app_scope(app["app_id"]):
        page = vector.list_chunks(file_ids=allowed_file_ids, workspace_ids=[workspace_id], limit=limit, cursor=cursor)

    chunks = []
    for document in page["documents"]:
        metadata = document.get("metadata") or {}
        file_id = metadata.get("file_id")
        file_record = visible_files.get(file_id, {})
        chunks.append({
            "id": document["id"],
            "file_id": file_id,
            "filename": file_record.get("filename") or metadata.get("filename"),
            "s3_url": file_record.get("s3_url") or metadata.get("s3_url"),
            "chunk_index": metadata.get("chunk_index"),
            "created_at": metadata.get("created_at"),
            "content": document.get("content", ""),
        })
    return {
        "chunks": chunks,
        "next_cursor": page.get("next_cursor"),
        "has_more": page.get("has_more", False),
    }
