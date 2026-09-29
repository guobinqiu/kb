from __future__ import annotations

import json

from .base import BaseDAO, _id, _now


class FilesDAO(BaseDAO):
    @staticmethod
    def _record(row) -> dict | None:
        result = BaseDAO._record(row)
        if result is not None and result.get("error") is not None:
            result["error"] = json.loads(result["error"])
        return result

    def create_file(self, **values) -> dict:
        file_id = values.get("id") or _id()
        return self._write_one(
            "INSERT INTO kb.files (id, workspace_id, filename, s3_url, mime_type, size_bytes, checksum, status, error, created_by, created_at, updated_at, indexed_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, NULL)",
            (file_id, values.get("workspace_id"), values["filename"], values.get("s3_url"), values.get("mime_type"), values.get("size_bytes"), values.get("checksum"), values.get("status", "uploaded"), json.dumps(values.get("error")) if values.get("error") is not None else None, values.get("created_by"), values.get("indexed_at")),
            "SELECT * FROM kb.files WHERE id = %s", (file_id,),
        )

    def get_file(self, file_id: str, include_deleted: bool = False) -> dict | None:
        clause = "" if include_deleted else " AND deleted_at IS NULL"
        return self._one("SELECT * FROM kb.files WHERE id = %s" + clause, (file_id,))

    def list_workspace_files(self, workspace_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kb.files WHERE workspace_id = %s AND deleted_at IS NULL ORDER BY created_at, id",
                (workspace_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def update_file(self, file_id: str, **values) -> dict | None:
        fields = ["workspace_id", "filename", "s3_url", "mime_type", "size_bytes", "checksum", "status", "error", "created_by", "indexed_at", "deleted_at"]
        fields = [field for field in fields if field in values]
        assignments = [f"{field} = %s" for field in fields] + ["updated_at = CURRENT_TIMESTAMP"]
        return self._write_one(
            "UPDATE kb.files SET " + ", ".join(assignments) + " WHERE id = %s",
            tuple(json.dumps(values[field]) if field == "error" and values[field] is not None else values[field] for field in fields) + (file_id,),
            "SELECT * FROM kb.files WHERE id = %s", (file_id,),
        )

    def apply_file_result(self, file_id: str, *, status: str, error, indexed_at, deleted: bool = False) -> dict | None:
        return self.update_file(file_id, status=status, error=error, indexed_at=indexed_at, deleted_at=_now() if deleted else None)
