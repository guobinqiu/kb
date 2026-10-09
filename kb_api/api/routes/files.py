from __future__ import annotations

import hashlib
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from kb_api.api.auth import current_user
from kb_api.api.permissions import (
    WORKSPACE_FILES_DELETE,
    WORKSPACE_FILES_READ,
    WORKSPACE_FILES_UPLOAD,
    can_change_workspace_file,
    has_workspace_permission,
)
from kb_api.api.rate_limit import require_index_rate_limit, require_rate_limit
from kb_api.api.schemas import FileUploadWorkspaceRequest, WorkspaceFileIndexRequest
from kb_api.api.services.rabbitmq import INDEX_TASK_QUEUE
from kb_api.api.telemetry import get_trace_id

router = APIRouter(prefix="/api/v1", tags=["files"])
SUPPORTED_FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"}


def _validate_file_type(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FILE_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or '(no extension)'}")


def _workspace(dao, workspace_id: str, user: dict) -> dict:
    workspace = dao.get_workspace(workspace_id)
    if not workspace or not dao.has_workspace_access(user, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _workspace_file(dao, workspace_id: str, file_id: str) -> dict:
    record = dao.get_file(file_id)
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


def _prepare_workspace_task(dao, record: dict, app: dict, operation: str) -> dict:
    task_id = str(uuid.uuid4())
    callback_token = secrets.token_urlsafe(32)
    dao.set_file_index_task(
        record["id"],
        task_id=task_id,
        token_hash=hashlib.sha256(callback_token.encode()).hexdigest(),
    )
    return _workspace_task(record, app, operation) | {
        "task_id": task_id,
        "callback_token": callback_token,
    }


def _queue_failure(exc: Exception) -> dict:
    return {
        "error": str(exc) or repr(exc),
        "service": "kb_api.queue",
        "retryable": True,
        "traceId": get_trace_id(),
    }


@router.get("/workspaces/{workspace_id}/files", dependencies=[Depends(require_rate_limit)])
def list_workspace_files(workspace_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_READ):
        raise HTTPException(status_code=403, detail="Workspace file access denied")
    return {"files": dao.list_workspace_files(workspace_id)}


@router.post("/workspaces/{workspace_id}/files/upload-url", dependencies=[Depends(require_rate_limit), Depends(require_index_rate_limit)])
def create_workspace_upload_url(
    workspace_id: str, request: Request, body: FileUploadWorkspaceRequest, user=Depends(current_user)
):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_UPLOAD):
        raise HTTPException(status_code=403, detail="Workspace file upload denied")
    if body.file_id:
        existing = _workspace_file(dao, workspace_id, body.file_id)
        if not can_change_workspace_file(dao, user, workspace, existing):
            raise HTTPException(status_code=403, detail="Workspace file update denied")
    file_id = body.file_id or str(uuid.uuid4())
    filename = Path(body.filename.replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="filename is required")
    _validate_file_type(filename)
    object_key = f"uploads/{workspace['app_id']}/{workspace_id}/{file_id}/{uuid.uuid4()}/{filename}"
    return {
        "file_id": file_id,
        "filename": filename,
        "content_type": body.content_type or "application/octet-stream",
        "s3_url": request.app.state.storage.object_url(object_key),
        "upload_url": request.app.state.storage.presign_put(object_key, expires_seconds=900),
    }


@router.post(
    "/workspaces/{workspace_id}/files/{file_id}/index",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_rate_limit), Depends(require_index_rate_limit)],
)
def index_workspace_file(
    workspace_id: str, file_id: str, request: Request, body: WorkspaceFileIndexRequest, user=Depends(current_user)
):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_UPLOAD):
        raise HTTPException(status_code=403, detail="Workspace file upload denied")
    prefix = request.app.state.storage.object_url(f"uploads/{workspace['app_id']}/{workspace_id}/{file_id}/")
    if not body.s3_url.startswith(prefix):
        raise HTTPException(status_code=400, detail="s3_url does not match file")
    filename = Path(body.filename.replace("\\", "/")).name
    if not filename or filename in {".", ".."} or Path(urlsplit(body.s3_url).path).name != filename:
        raise HTTPException(status_code=400, detail="filename does not match s3_url")
    _validate_file_type(filename)
    existing = dao.get_file(file_id)
    if existing and existing.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="File not found")
    if existing and not can_change_workspace_file(dao, user, workspace, existing):
        raise HTTPException(status_code=403, detail="Workspace file update denied")
    try:
        stored = request.app.state.storage.stat(body.s3_url)
        checksum = request.app.state.storage.checksum(body.s3_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Uploaded object is unavailable: {exc}") from exc
    metadata = {
        "filename": filename,
        "s3_url": body.s3_url,
        "mime_type": body.content_type or getattr(stored, "content_type", None),
        "size_bytes": stored.size,
        "checksum": checksum,
    }
    if existing and existing["status"] == "indexed" and existing.get("checksum") == checksum:
        return dao.update_file(file_id, **metadata)
    if existing and existing["s3_url"] == body.s3_url and existing["status"] == "indexing" and existing.get("checksum") == checksum:
        return existing
    if existing:
        record = dao.update_file(file_id, status="indexing", error=None, indexed_at=None, **metadata)
    else:
        record = dao.create_file(
            id=file_id,
            workspace_id=workspace_id,
            status="indexing",
            error=None,
            indexed_at=None,
            created_by=user["id"],
            **metadata,
        )
    app = dao.get_app(workspace["app_id"])
    try:
        request.app.state.queue.publish(INDEX_TASK_QUEUE, _prepare_workspace_task(dao, record, app, "index"))
    except Exception as exc:
        error = _queue_failure(exc)
        dao.update_file(file_id, status="failed", error=error, indexed_at=None)
        raise HTTPException(status_code=503, detail=error) from exc
    return record


@router.get("/workspaces/{workspace_id}/files/{file_id}", dependencies=[Depends(require_rate_limit)])
def get_workspace_file(workspace_id: str, file_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_READ):
        raise HTTPException(status_code=403, detail="Workspace file access denied")
    return _workspace_file(dao, workspace_id, file_id)


@router.delete("/workspaces/{workspace_id}/files/{file_id}", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_rate_limit)])
def delete_workspace_file(workspace_id: str, file_id: str, request: Request, user=Depends(current_user)):
    dao = request.app.state.dao
    workspace = _workspace(dao, workspace_id, user)
    record = _workspace_file(dao, workspace_id, file_id)
    if not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_DELETE) or not can_change_workspace_file(dao, user, workspace, record):
        raise HTTPException(status_code=403, detail="Workspace file delete denied")
    record = dao.update_file(file_id, status="deleting", error=None)
    app = dao.get_app(workspace["app_id"])
    try:
        request.app.state.queue.publish(INDEX_TASK_QUEUE, _prepare_workspace_task(dao, record, app, "delete"))
    except Exception as exc:
        error = _queue_failure(exc)
        dao.update_file(file_id, status="delete_failed", error=error)
        raise HTTPException(status_code=503, detail=error) from exc
    return record


def apply_index_result(dao, storage, message: dict, *, task_id: str, token_hash: str) -> bool:
    file_id = message.get("file_id")
    operation = message.get("operation")
    if not isinstance(file_id, str) or operation not in {"index", "delete"}:
        raise ValueError("result requires operation and file_id")
    existing = dao.get_file(file_id, include_deleted=True)
    if not existing:
        return False
    incoming_status = message.get("status")
    success = message.get("success")
    if operation == "delete":
        deleted = incoming_status in {"deleted", "success"} or success is True
        result_status = "deleting" if deleted else "delete_failed"
    else:
        deleted = False
        result_status = "indexed" if incoming_status in {"indexed", "success"} or success is True else "failed"
    updated = dao.apply_file_result(
        file_id,
        task_id=task_id,
        token_hash=token_hash,
        status=result_status,
        error=message.get("error"),
        indexed_at=message.get("indexed_at"),
        deleted=deleted,
    )
    if not updated:
        return False
    if deleted and existing.get("s3_url"):
        storage.delete(existing["s3_url"])
    return True


@router.post(
    "/index-results",
    status_code=204,
)
def update_index_result(body: dict, request: Request):
    file_id = body.get("file_id")
    operation = body.get("operation")
    task_id = body.get("task_id")
    callback_token = body.get("callback_token")
    if not all(isinstance(value, str) and value for value in (file_id, operation, task_id, callback_token)):
        raise HTTPException(status_code=401, detail="Invalid callback credentials")
    token_hash = hashlib.sha256(callback_token.encode()).hexdigest()
    if not apply_index_result(
        request.app.state.dao,
        request.app.state.storage,
        body,
        task_id=task_id,
        token_hash=token_hash,
    ):
        raise HTTPException(status_code=401, detail="Invalid callback credentials")
    return Response(status_code=204)
