from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from kb_api.auth import current_user
from kb_api.api.schemas import FileUploadWorkspaceComplete, FileUploadWorkspaceRequest
from kb_api.permissions import (
    WORKSPACE_FILES_DELETE,
    WORKSPACE_FILES_READ,
    WORKSPACE_FILES_UPLOAD,
    can_change_workspace_file,
    has_workspace_permission,
)
from kb_api.queue import INDEX_TASK_QUEUE
from kb_api.rate_limit import require_index_rate_limit, require_rate_limit
from kb_api.telemetry import get_trace_id


router = APIRouter(prefix="/api/v1", tags=["files"], dependencies=[Depends(require_rate_limit)])


def _workspace(repository, workspace_id: str, user: dict) -> dict:
    workspace = repository.get_workspace(workspace_id)
    if not workspace or not repository.has_workspace_access(user, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _workspace_file(repository, workspace_id: str, file_id: str) -> dict:
    record = repository.get_file(file_id)
    if not record or record.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="File not found")
    return record


def _workspace_task(record: dict, app: dict, operation: str) -> dict:
    return {
        "operation": operation,
        "app_id": app["app_id"],
        "workspace_id": record["workspace_id"],
        "file_id": record["id"],
        "s3_url": record["s3_url"],
        "filename": record["filename"],
    }


def _queue_failure(exc: Exception) -> dict:
    return {
        "error": str(exc) or repr(exc),
        "service": "kb_api.queue",
        "retryable": True,
        "traceId": get_trace_id(),
    }


@router.get("/workspaces/{workspace_id}/files")
def list_workspace_files(workspace_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    workspace = _workspace(repository, workspace_id, user)
    if not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_READ):
        raise HTTPException(status_code=403, detail="Workspace file access denied")
    return {"files": repository.list_workspace_files(workspace_id)}


@router.post("/workspaces/{workspace_id}/files/upload-url", dependencies=[Depends(require_index_rate_limit)])
def create_workspace_upload_url(
    workspace_id: str, request: Request, body: FileUploadWorkspaceRequest, user=Depends(current_user)
):
    repository = request.app.state.repository
    workspace = _workspace(repository, workspace_id, user)
    if not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_UPLOAD):
        raise HTTPException(status_code=403, detail="Workspace file upload denied")
    if body.file_id:
        existing = _workspace_file(repository, workspace_id, body.file_id)
        if not can_change_workspace_file(repository, user, workspace, existing):
            raise HTTPException(status_code=403, detail="Workspace file update denied")
    file_id = body.file_id or str(uuid.uuid4())
    filename = Path(body.filename.replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="filename is required")
    object_key = f"uploads/{workspace['app_id']}/{workspace_id}/{file_id}/{uuid.uuid4()}/{filename}"
    return {
        "file_id": file_id,
        "filename": filename,
        "content_type": body.content_type or "application/octet-stream",
        "object_key": object_key,
        "upload_url": request.app.state.storage.presign_put(object_key, expires_seconds=900),
    }


@router.post(
    "/workspaces/{workspace_id}/files/{file_id}/complete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_index_rate_limit)],
)
def complete_workspace_upload(
    workspace_id: str, file_id: str, request: Request, body: FileUploadWorkspaceComplete, user=Depends(current_user)
):
    repository = request.app.state.repository
    workspace = _workspace(repository, workspace_id, user)
    if not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_UPLOAD):
        raise HTTPException(status_code=403, detail="Workspace file upload denied")
    if not body.object_key.startswith(f"uploads/{workspace['app_id']}/{workspace_id}/{file_id}/"):
        raise HTTPException(status_code=400, detail="object_key does not match file")
    filename = Path(body.filename.replace("\\", "/")).name
    if not filename or filename in {".", ".."} or Path(body.object_key).name != filename:
        raise HTTPException(status_code=400, detail="filename does not match object_key")
    existing = repository.get_file(file_id)
    if existing and existing.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="File not found")
    if existing and not can_change_workspace_file(repository, user, workspace, existing):
        raise HTTPException(status_code=403, detail="Workspace file update denied")
    try:
        stored = request.app.state.storage.stat(body.object_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded object is unavailable: {exc}") from exc
    metadata = {
        "filename": filename,
        "object_key": body.object_key,
        "s3_url": request.app.state.storage.object_url(body.object_key),
        "mime_type": body.content_type or getattr(stored, "content_type", None),
        "size_bytes": stored.size,
        "checksum": None,
    }
    if existing and existing["object_key"] == body.object_key:
        return existing
    if existing:
        record = repository.update_file(file_id, status="indexing", error=None, indexed_at=None, **metadata)
    else:
        record = repository.create_file(
            id=file_id,
            workspace_id=workspace_id,
            status="indexing",
            error=None,
            indexed_at=None,
            created_by=user["id"],
            **metadata,
        )
    app = repository.get_app(workspace["app_id"])
    try:
        request.app.state.queue.publish(INDEX_TASK_QUEUE, _workspace_task(record, app, "index"))
    except Exception as exc:
        error = _queue_failure(exc)
        repository.update_file(file_id, status="failed", error=error, indexed_at=None)
        raise HTTPException(status_code=503, detail=error) from exc
    return record


@router.get("/workspaces/{workspace_id}/files/{file_id}")
def get_workspace_file(workspace_id: str, file_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    workspace = _workspace(repository, workspace_id, user)
    if not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_READ):
        raise HTTPException(status_code=403, detail="Workspace file access denied")
    return _workspace_file(repository, workspace_id, file_id)


@router.delete("/workspaces/{workspace_id}/files/{file_id}", status_code=status.HTTP_202_ACCEPTED)
def delete_workspace_file(workspace_id: str, file_id: str, request: Request, user=Depends(current_user)):
    repository = request.app.state.repository
    workspace = _workspace(repository, workspace_id, user)
    record = _workspace_file(repository, workspace_id, file_id)
    if not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_DELETE) or not can_change_workspace_file(repository, user, workspace, record):
        raise HTTPException(status_code=403, detail="Workspace file delete denied")
    record = repository.update_file(file_id, status="deleting", error=None)
    app = repository.get_app(workspace["app_id"])
    try:
        request.app.state.queue.publish(INDEX_TASK_QUEUE, _workspace_task(record, app, "delete"))
    except Exception as exc:
        error = _queue_failure(exc)
        repository.update_file(file_id, status="delete_failed", error=error)
        raise HTTPException(status_code=503, detail=error) from exc
    return record
