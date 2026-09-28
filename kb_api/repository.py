from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone

_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


class PostgresRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _record(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for key, value in result.items():
            if isinstance(value, (datetime, uuid.UUID)):
                result[key] = str(value)
        return result

    def close(self) -> None:
        pass

    def create_app(self, name: str, app_id: str, api_key: str | None = None) -> tuple[dict, dict]:
        with self._connect() as connection:
            app = connection.execute(
                "INSERT INTO kb.apps (id, app_id, name, api_key, created_at, updated_at) VALUES (%s, %s, %s, %s, now(), now()) RETURNING *",
                (_id(), app_id, name, api_key or secrets.token_urlsafe(32)),
            ).fetchone()
            org = connection.execute(
                "INSERT INTO kb.orgs (id, app_id, parent_id, name, created_at, updated_at) VALUES (%s, %s, NULL, %s, now(), now()) RETURNING *",
                (_id(), app["id"], name),
            ).fetchone()
            return self._record(app), self._record(org)

    def _descendants_cte(self, include_disabled: bool = False) -> str:
        active = "" if include_disabled else " AND deleted_at IS NULL"
        child_active = "" if include_disabled else " AND n.deleted_at IS NULL"
        return f"WITH RECURSIVE descendants AS (SELECT id FROM kb.orgs WHERE id = %s{active} UNION ALL SELECT n.id FROM kb.orgs n JOIN descendants d ON n.parent_id = d.id{child_active})"

    def descendant_org_ids(self, org_id: str) -> set[str]:
        if not self.is_active_org(org_id):
            return set()
        with self._connect() as connection:
            rows = connection.execute(self._descendants_cte() + " SELECT id FROM descendants", (org_id,)).fetchall()
        return {str(row["id"]) for row in rows}

    def subtree_org_ids(self, org_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(self._descendants_cte(True) + " SELECT id FROM descendants", (org_id,)).fetchall()
        return {str(row["id"]) for row in rows}

    def is_active_org(self, org_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "WITH RECURSIVE ancestors AS (SELECT id, parent_id, deleted_at FROM kb.orgs WHERE id = %s UNION ALL SELECT n.id, n.parent_id, n.deleted_at FROM kb.orgs n JOIN ancestors a ON n.id = a.parent_id) SELECT count(*) > 0 AND bool_and(deleted_at IS NULL) AS active FROM ancestors",
                (org_id,),
            ).fetchone()
        return bool(row["active"])

    def app_org_ids(self, app_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "WITH RECURSIVE active AS (SELECT id FROM kb.orgs WHERE app_id = %s AND parent_id IS NULL AND deleted_at IS NULL UNION ALL SELECT n.id FROM kb.orgs n JOIN active a ON n.parent_id = a.id WHERE n.deleted_at IS NULL) SELECT id FROM active",
                (app_id,),
            ).fetchall()
        return {str(row["id"]) for row in rows}

    def list_apps(self, user_org_id: str | None, include_disabled: bool = False) -> list[dict]:
        with self._connect() as connection:
            if user_org_id is None:
                rows = connection.execute("SELECT * FROM kb.apps ORDER BY created_at").fetchall()
            else:
                rows = connection.execute(
                    "SELECT a.* FROM kb.apps a JOIN kb.orgs o ON o.app_id = a.id WHERE o.id = %s ORDER BY a.created_at",
                    (user_org_id,),
                ).fetchall()
        return [self._record(row) for row in rows]

    def get_app(self, app_id: str) -> dict | None:
        return self._one("SELECT * FROM kb.apps WHERE id = %s", (app_id,))

    def get_app_by_business_id(self, app_id: str) -> dict | None:
        return self._one("SELECT * FROM kb.apps WHERE app_id = %s", (app_id,))

    def get_app_by_api_key(self, api_key: str) -> dict | None:
        return self._one("SELECT * FROM kb.apps WHERE api_key = %s", (api_key,))

    def update_app(self, app_id: str, name: str) -> dict | None:
        return self._one("UPDATE kb.apps SET name = %s, updated_at = now() WHERE id = %s RETURNING *", (name, app_id))

    def delete_app(self, app_id: str) -> bool:
        return self._execute("DELETE FROM kb.apps WHERE id = %s", (app_id,))

    def create_workspace(self, app_id: str, name: str, creator_id: str | None = None) -> dict:
        with self._connect() as connection:
            workspace = connection.execute(
                "INSERT INTO kb.workspaces (id, app_id, name, created_at, updated_at) VALUES (%s, %s, %s, now(), now()) RETURNING *",
                (_id(), app_id, name),
            ).fetchone()
            if creator_id is not None:
                connection.execute(
                    "INSERT INTO kb.workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, 'admin')",
                    (_id(), workspace["id"], creator_id),
                )
            return self._record(workspace)

    def get_workspace(self, workspace_id: str) -> dict | None:
        return self._one("SELECT * FROM kb.workspaces WHERE id = %s", (workspace_id,))

    def list_workspaces(self, app_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kb.workspaces WHERE app_id = %s ORDER BY created_at, id",
                (app_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def update_workspace(self, workspace_id: str, name: str) -> dict | None:
        return self._one(
            "UPDATE kb.workspaces SET name = %s, updated_at = now() WHERE id = %s RETURNING *",
            (name, workspace_id),
        )

    def delete_workspace(self, workspace_id: str) -> bool:
        return self._execute("DELETE FROM kb.workspaces WHERE id = %s", (workspace_id,))

    def list_workspace_members(self, workspace_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.workspace_id, 'user' AS type, m.user_id,
                       u.org_id, u.name, m.role
                FROM kb.workspace_user m JOIN kb.users u ON u.id = m.user_id
                WHERE m.workspace_id = %s
                UNION ALL
                SELECT m.id, m.workspace_id, 'org' AS type, NULL AS user_id,
                       m.org_id, o.name, m.role
                FROM kb.workspace_org m JOIN kb.orgs o ON o.id = m.org_id
                WHERE m.workspace_id = %s
                ORDER BY type, id
                """,
                (workspace_id, workspace_id),
            ).fetchall()
        return [self._record(row) for row in rows]

    def add_workspace_member(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: str = "editor",
    ) -> dict:
        self._validate_workspace_role(role)
        with self._connect() as connection:
            self._lock_workspace(connection, workspace_id)
            if role != "admin":
                member = connection.execute(
                    "SELECT id FROM kb.workspace_user WHERE workspace_id = %s AND user_id = %s",
                    (workspace_id, user_id),
                ).fetchone()
                if member is not None:
                    self._retain_workspace_admin(connection, workspace_id, str(member["id"]))
            return self._record(connection.execute(
                "INSERT INTO kb.workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, %s) ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = EXCLUDED.role RETURNING *",
                (_id(), workspace_id, user_id, role),
            ).fetchone())

    def update_workspace_member(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role)
        with self._connect() as connection:
            self._lock_workspace(connection, workspace_id)
            if role != "admin":
                self._retain_workspace_admin(connection, workspace_id, member_id)
            return self._record(connection.execute(
                "UPDATE kb.workspace_user SET role = %s WHERE workspace_id = %s AND id = %s RETURNING *",
                (role, workspace_id, member_id),
            ).fetchone())

    def delete_workspace_member(self, workspace_id: str, member_id: str) -> bool:
        with self._connect() as connection:
            self._lock_workspace(connection, workspace_id)
            self._retain_workspace_admin(connection, workspace_id, member_id)
            return connection.execute(
                "DELETE FROM kb.workspace_user WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).rowcount > 0

    def add_workspace_org(self, workspace_id: str, *, org_id: str, role: str = "viewer") -> dict:
        self._validate_workspace_role(role, org=True)
        return self._one(
            "INSERT INTO kb.workspace_org (id, workspace_id, org_id, role) VALUES (%s, %s, %s, %s) ON CONFLICT (workspace_id, org_id) DO UPDATE SET role = EXCLUDED.role RETURNING *",
            (_id(), workspace_id, org_id, role),
        )

    def update_workspace_org(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role, org=True)
        return self._one(
            "UPDATE kb.workspace_org SET role = %s WHERE workspace_id = %s AND id = %s RETURNING *",
            (role, workspace_id, member_id),
        )

    def delete_workspace_org(self, workspace_id: str, member_id: str) -> bool:
        return self._execute(
            "DELETE FROM kb.workspace_org WHERE workspace_id = %s AND id = %s",
            (workspace_id, member_id),
        )

    @staticmethod
    def _validate_workspace_role(role: str, *, org: bool = False) -> None:
        allowed = ("editor", "viewer") if org else ("admin", "editor", "viewer")
        if role not in allowed:
            raise ValueError("Invalid workspace role")

    @staticmethod
    def _lock_workspace(connection, workspace_id: str) -> None:
        connection.execute("SELECT id FROM kb.workspaces WHERE id = %s FOR UPDATE", (workspace_id,)).fetchone()

    @staticmethod
    def _workspace_active_orgs_cte() -> str:
        return """
            WITH RECURSIVE active_orgs AS (
                SELECT o.id, o.app_id FROM kb.orgs o
                JOIN kb.workspaces w ON w.app_id = o.app_id
                WHERE w.id = %s AND o.parent_id IS NULL AND o.deleted_at IS NULL
                UNION ALL
                SELECT o.id, o.app_id FROM kb.orgs o
                JOIN active_orgs parent ON o.parent_id = parent.id AND o.app_id = parent.app_id
                WHERE o.deleted_at IS NULL
            )
        """

    def _retain_workspace_admin(self, connection, workspace_id: str, member_id: str) -> None:
        # The workspace lock serializes member writes; read admins after acquiring it.
        admins = connection.execute(
            self._workspace_active_orgs_cte() + """
            SELECT m.id FROM kb.workspace_user m
            JOIN kb.users u ON u.id = m.user_id AND u.deleted_at IS NULL
            LEFT JOIN active_orgs o ON o.id = u.org_id
            WHERE m.workspace_id = %s AND m.role = 'admin'
              AND (o.id IS NOT NULL OR (u.role = 'owner' AND u.org_id IS NULL))
            """,
            (workspace_id, workspace_id),
        ).fetchall()
        if len(admins) == 1 and uuid.UUID(str(admins[0]["id"])) == uuid.UUID(str(member_id)):
            raise ValueError("Workspace must retain an administrator")

    def get_workspace_role(self, user: dict, workspace_id: str) -> str | None:
        if not user.get("id") or user.get("deleted_at") is not None:
            return None
        row = self._one(
            self._workspace_active_orgs_cte() + """
            SELECT COALESCE(personal.role, department.role) AS role
            FROM kb.users u
            LEFT JOIN active_orgs o ON o.id = u.org_id
            LEFT JOIN kb.workspace_user personal ON personal.user_id = u.id AND personal.workspace_id = %s
            LEFT JOIN kb.workspace_org department ON department.org_id = u.org_id AND department.workspace_id = %s
            WHERE u.id = %s AND u.deleted_at IS NULL
              AND (o.id IS NOT NULL OR (u.role = 'owner' AND u.org_id IS NULL))
            """,
            (workspace_id, workspace_id, workspace_id, user["id"]),
        )
        return row["role"] if row is not None else None

    def has_workspace_access(self, user: dict, workspace_id: str) -> bool:
        return self.get_workspace_role(user, workspace_id) is not None

    def get_org(self, org_id: str) -> dict | None:
        return self._one("SELECT * FROM kb.orgs WHERE id = %s", (org_id,))

    def list_orgs(self, user_org_id: str | None, include_disabled: bool = False) -> list[dict]:
        if user_org_id is not None:
            selected_org = self.get_org(user_org_id)
            if not selected_org:
                return []
            return self._list_app_orgs(selected_org["app_id"], include_disabled=include_disabled)
        active = "" if include_disabled else " AND deleted_at IS NULL"
        child_active = "" if include_disabled else " WHERE n.deleted_at IS NULL"
        with self._connect() as connection:
            rows = connection.execute(
                f"WITH RECURSIVE org_tree AS (SELECT * FROM kb.orgs WHERE parent_id IS NULL{active} UNION ALL SELECT n.* FROM kb.orgs n JOIN org_tree parent ON n.parent_id = parent.id{child_active}) SELECT * FROM org_tree ORDER BY created_at, id"
            ).fetchall()
        return [self._record(row) for row in rows]

    def list_app_orgs(self, app_id: str) -> list[dict]:
        return self._list_app_orgs(app_id, include_disabled=False)

    def _list_app_orgs(self, app_id: str, *, include_disabled: bool) -> list[dict]:
        active = "" if include_disabled else " AND deleted_at IS NULL"
        child_active = "" if include_disabled else " AND n.deleted_at IS NULL"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH RECURSIVE app_tree AS (
                    SELECT * FROM kb.orgs
                    WHERE app_id = %s AND parent_id IS NULL{active}
                    UNION ALL
                    SELECT n.* FROM kb.orgs n
                    JOIN app_tree parent ON n.parent_id = parent.id
                    WHERE n.app_id = %s{child_active}
                )
                SELECT * FROM app_tree ORDER BY created_at, id
                """,
                (app_id, app_id),
            ).fetchall()
        return [self._record(row) for row in rows]

    def create_org(self, app_id: str, parent_id: str, name: str) -> dict:
        return self._one(
            "INSERT INTO kb.orgs (id, app_id, parent_id, name, created_at, updated_at) VALUES (%s, %s, %s, %s, now(), now()) RETURNING *",
            (_id(), app_id, parent_id, name),
        )

    def update_org(self, org_id: str, *, name: str | None = None, parent_id: str | None = None, deleted_at=_UNSET) -> dict | None:
        org = self.get_org(org_id)
        if not org:
            return None
        return self._one("UPDATE kb.orgs SET name = %s, parent_id = %s, deleted_at = %s, updated_at = now() WHERE id = %s RETURNING *", (name or org["name"], parent_id or org["parent_id"], org["deleted_at"] if deleted_at is _UNSET else deleted_at, org_id))

    def delete_org(self, org_id: str) -> bool:
        return self._execute("UPDATE kb.orgs SET deleted_at = now(), updated_at = now() WHERE id = %s AND parent_id IS NOT NULL", (org_id,))

    def count_subtree_resources(self, org_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                self._descendants_cte(True) + " SELECT (SELECT count(*) - 1 FROM descendants) + (SELECT count(*) FROM kb.users WHERE org_id IN (SELECT id FROM descendants)) AS total",
                (org_id,),
            ).fetchone()
        return max(0, row["total"])

    def purge_org(self, org_id: str) -> bool:
        if self.count_subtree_resources(org_id):
            return False
        return self._execute("DELETE FROM kb.orgs WHERE id = %s AND parent_id IS NOT NULL AND deleted_at IS NOT NULL", (org_id,))

    def create_user(self, *, org_id: str | None, name: str, password_hash: str | None, role: str = "member") -> dict:
        return self._one(
            "INSERT INTO kb.users (id, org_id, name, password_hash, role, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, now(), now()) RETURNING *",
            (_id(), org_id, name, password_hash, role),
        )

    def get_user(self, user_id: str) -> dict | None:
        return self._one("SELECT * FROM kb.users WHERE id = %s", (user_id,))

    def get_user_by_name(self, name: str) -> dict | None:
        return self._one("SELECT * FROM kb.users WHERE name = %s", (name,))

    def list_users(self, user_org_id: str | None, include_disabled: bool = False) -> list[dict]:
        active_user = "" if include_disabled else " WHERE u.deleted_at IS NULL"
        with self._connect() as connection:
            if user_org_id is None:
                rows = connection.execute("SELECT u.* FROM kb.users u" + active_user + " ORDER BY u.created_at").fetchall()
            else:
                rows = connection.execute(self._descendants_cte(include_disabled) + " SELECT u.* FROM kb.users u JOIN descendants d ON d.id = u.org_id" + active_user + " ORDER BY u.created_at", (user_org_id,)).fetchall()
        return [_public_user(self._record(row)) for row in rows]

    def list_org_users(self, org_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM kb.users WHERE org_id = %s AND deleted_at IS NULL ORDER BY created_at, id",
                (org_id,),
            ).fetchall()
        return [_public_user(self._record(row)) for row in rows]

    def list_workspace_users(self, workspace_id: str, *, org_id: str | None = None,
                             query: str = "", page: int = 1, page_size: int = 20) -> dict:
        scope = """
            FROM kb.users u JOIN active_orgs o ON o.id = u.org_id
            WHERE u.deleted_at IS NULL AND strpos(lower(u.name), lower(%s)) > 0
        """
        params = (workspace_id, query)
        if org_id is not None:
            scope += " AND u.org_id = %s"
            params += (org_id,)
        with self._connect() as connection:
            total = connection.execute(
                self._workspace_active_orgs_cte() + "SELECT count(*) AS total " + scope,
                params,
            ).fetchone()["total"]
            rows = connection.execute(
                self._workspace_active_orgs_cte() + "SELECT u.id, u.org_id, u.name " + scope
                + " ORDER BY u.name, u.id LIMIT %s OFFSET %s",
                params + (page_size, (page - 1) * page_size),
            ).fetchall()
        return {"users": [self._record(row) for row in rows], "total": total,
                "page": page, "page_size": page_size}

    def update_user(self, user_id: str, *, org_id=_UNSET, password_hash: str | None = None, role: str | None = None, deleted_at=_UNSET) -> dict | None:
        user = self.get_user(user_id)
        if not user:
            return None
        row = self._one(
            "UPDATE kb.users SET org_id = %s, password_hash = %s, role = %s, deleted_at = %s, updated_at = now() WHERE id = %s RETURNING *",
            (user["org_id"] if org_id is _UNSET else org_id, password_hash or user["password_hash"], role or user["role"], user["deleted_at"] if deleted_at is _UNSET else deleted_at, user_id),
        )
        return _public_user(row)

    def delete_user(self, user_id: str) -> bool:
        return self._execute("UPDATE kb.users SET deleted_at = now(), updated_at = now() WHERE id = %s", (user_id,))

    def create_file(self, **values) -> dict:
        return self._one(
            "INSERT INTO kb.files (id, workspace_id, filename, object_key, s3_url, mime_type, size_bytes, checksum, status, error, created_by, created_at, updated_at, indexed_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), %s, NULL) RETURNING *",
            (values.get("id") or _id(), values.get("workspace_id"), values["filename"], values.get("object_key"), values.get("s3_url"), values.get("mime_type"), values.get("size_bytes"), values.get("checksum"), values.get("status", "uploaded"), json.dumps(values.get("error")) if values.get("error") is not None else None, values.get("created_by"), values.get("indexed_at")),
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
        record = self.get_file(file_id, include_deleted=True)
        if not record:
            return None
        fields = ["workspace_id", "filename", "object_key", "s3_url", "mime_type", "size_bytes", "checksum", "status", "error", "created_by", "indexed_at", "deleted_at"]
        merged = {field: values.get(field, record.get(field)) for field in fields}
        return self._one(
            "UPDATE kb.files SET workspace_id=%s, filename=%s, object_key=%s, s3_url=%s, mime_type=%s, size_bytes=%s, checksum=%s, status=%s, error=%s, created_by=%s, indexed_at=%s, deleted_at=%s, updated_at=now() WHERE id=%s RETURNING *",
            tuple(json.dumps(merged[field]) if field == "error" and merged[field] is not None else merged[field] for field in fields) + (file_id,),
        )

    def apply_file_result(self, file_id: str, *, status: str, error, indexed_at, deleted: bool = False) -> dict | None:
        return self.update_file(file_id, status=status, error=error, indexed_at=indexed_at, deleted_at=_now() if deleted else None)

    def _one(self, query: str, params: tuple) -> dict | None:
        with self._connect() as connection:
            return self._record(connection.execute(query, params).fetchone())

    def _execute(self, query: str, params: tuple) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            return cursor.rowcount > 0
