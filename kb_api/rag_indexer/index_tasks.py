from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from kb_api.rag_indexer.common.upstream import UpstreamServiceError, _task_trace_id, get_trace_id
from kb_api.rag_indexer.clients.minio import presign_object
from kb_api.rag_indexer.core.index import index_presigned_file


@dataclass(frozen=True)
class IndexTask:
    operation: str
    app_id: str
    workspace_id: str
    file_id: str
    s3_url: str | None = None
    filename: str | None = None

    def __post_init__(self):
        if self.operation not in {"index", "delete"}:
            raise ValueError("operation must be index or delete")
        for name in ("app_id", "workspace_id", "file_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.operation == "index" and (not self.s3_url or not self.filename):
            raise ValueError("s3_url and filename are required for index operation")

    @classmethod
    def from_dict(cls, value: dict) -> "IndexTask":
        if "workspace_key" in value:
            raise ValueError("workspace_key is not supported")
        return cls(
            operation=value.get("operation", ""),
            app_id=value.get("app_id", ""),
            workspace_id=value.get("workspace_id", ""),
            file_id=value.get("file_id", ""),
            s3_url=value.get("s3_url"),
            filename=value.get("filename"),
        )


class ResultCallback(Protocol):
    def post(self, value: dict) -> None:
        ...


class IndexTaskConsumer:
    def __init__(self, state, callback: ResultCallback):
        self.state = state
        self.callback = callback

    def handle(self, value: dict) -> dict:
        token = _task_trace_id.set(uuid4().hex)
        try:
            result = task_result(self.state, value)
            self.callback.post(result)
            return result
        finally:
            _task_trace_id.reset(token)


def process_index_task(state, task: IndexTask) -> dict:
    with state.vector_client.app_scope(task.app_id):
        if task.operation == "delete":
            deleted_chunks = state.vector_client.delete_file_chunks(task.file_id)
            return _result(task, deleted_chunks=deleted_chunks)

        state.vector_client.ensure_app_collection(task.app_id)
        chunk_count, file_size = index_presigned_file(
            state,
            file_id=task.file_id,
            presigned_url=_presigned_url(state, task.s3_url),
            s3_url=task.s3_url,
            filename=task.filename,
            extra_metadata={"workspace_id": task.workspace_id},
        )
        return _result(task, chunk_count=chunk_count, file_size=file_size)


def task_result(state, value: dict) -> dict:
    operation = value.get("operation")
    file_id = value.get("file_id")
    try:
        return process_index_task(state, IndexTask.from_dict(value))
    except UpstreamServiceError as exc:
        return {
            "operation": operation,
            "file_id": file_id,
            "success": False,
            "status": _failure_status(operation),
            "error": exc.detail(),
            "retryable": exc.retryable,
            "indexed_at": None,
        }
    except Exception as exc:
        trace_id = get_trace_id()
        return {
            "operation": operation,
            "file_id": file_id,
            "success": False,
            "status": _failure_status(operation),
            "error": {
                "error": str(exc) or None,
                "service": "rag_indexer",
                "retryable": False,
                "traceId": trace_id,
            },
            "retryable": False,
            "indexed_at": None,
        }


def _presigned_url(state, s3_url: str) -> str:
    return presign_object(state.config.storage, s3_url)


def _result(task: IndexTask, **values) -> dict:
    return {
        "operation": task.operation,
        "file_id": task.file_id,
        "success": True,
        "status": "indexed" if task.operation == "index" else "deleted",
        "error": None,
        "retryable": False,
        "indexed_at": datetime.now(timezone.utc).isoformat() if task.operation == "index" else None,
        **values,
    }


def _failure_status(operation: str | None) -> str:
    return "delete_failed" if operation == "delete" else "failed"
