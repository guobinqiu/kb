from __future__ import annotations


def apply_index_result(repository, storage, message: dict) -> None:
    file_id = message.get("file_id")
    operation = message.get("operation")
    if not isinstance(file_id, str) or operation not in {"index", "delete"}:
        raise ValueError("result requires operation and file_id")
    existing = repository.get_file(file_id, include_deleted=True)
    if not existing:
        return
    incoming_status = message.get("status")
    success = message.get("success")
    if operation == "delete":
        deleted = incoming_status in {"deleted", "success"} or success is True
        result_status = "deleting" if deleted else "delete_failed"
    else:
        deleted = False
        result_status = "indexed" if incoming_status in {"indexed", "success"} or success is True else "failed"
    repository.apply_file_result(
        file_id,
        status=result_status,
        error=message.get("error"),
        indexed_at=message.get("indexed_at"),
        deleted=deleted,
    )
    if deleted and existing.get("object_key"):
        storage.delete(existing["object_key"])
