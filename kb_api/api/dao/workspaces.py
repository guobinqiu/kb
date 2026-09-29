from __future__ import annotations

import uuid

from .base import BaseDAO, _id


class WorkspacesDAO(BaseDAO):
    def create_workspace(self, app_id: str, name: str, creator_id: str | None = None) -> dict:
        with self._connect() as connection:
            workspace_id = _id()
            connection.execute(
                "INSERT INTO kb.workspaces (id, app_id, name, created_by, created_at, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (workspace_id, app_id, name, creator_id),
            )
            if creator_id is not None:
                connection.execute(
                    "INSERT INTO kb.workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, 'admin')",
                    (_id(), workspace_id, creator_id),
                )
            workspace = connection.execute("SELECT * FROM kb.workspaces WHERE id = %s", (workspace_id,)).fetchone()
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
        return self._write_one(
            "UPDATE kb.workspaces SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (name, workspace_id), "SELECT * FROM kb.workspaces WHERE id = %s", (workspace_id,),
        )

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._connect() as connection:
            workspace = connection.execute("SELECT id FROM kb.workspaces WHERE id = %s", (workspace_id,)).fetchone()
            if not workspace:
                return False
            if connection.execute(
                "SELECT id FROM kb.files WHERE workspace_id = %s AND deleted_at IS NULL",
                (workspace_id,),
            ).fetchone():
                raise ValueError("Workspace contains files")
            connection.execute("DELETE FROM kb.workspace_user WHERE workspace_id = %s", (workspace_id,))
            connection.execute("DELETE FROM kb.workspace_org WHERE workspace_id = %s", (workspace_id,))
            connection.execute("DELETE FROM kb.files WHERE workspace_id = %s", (workspace_id,))
            return connection.execute("DELETE FROM kb.workspaces WHERE id = %s", (workspace_id,)).rowcount > 0

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
            member = connection.execute(
                "SELECT id FROM kb.workspace_user WHERE workspace_id = %s AND user_id = %s",
                (workspace_id, user_id),
            ).fetchone()
            if role != "admin":
                if member is not None:
                    self._retain_workspace_admin(connection, workspace_id, str(member["id"]))
            if member is None:
                member_id = _id()
                connection.execute(
                    "INSERT INTO kb.workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, %s)",
                    (member_id, workspace_id, user_id, role),
                )
            else:
                member_id = member["id"]
                connection.execute("UPDATE kb.workspace_user SET role = %s WHERE id = %s", (role, member_id))
            return self._record(connection.execute("SELECT * FROM kb.workspace_user WHERE id = %s", (member_id,)).fetchone())

    def update_workspace_member(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role)
        with self._connect() as connection:
            if role != "admin":
                self._retain_workspace_admin(connection, workspace_id, member_id)
            connection.execute(
                "UPDATE kb.workspace_user SET role = %s WHERE workspace_id = %s AND id = %s",
                (role, workspace_id, member_id),
            )
            return self._record(connection.execute(
                "SELECT * FROM kb.workspace_user WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).fetchone())

    def delete_workspace_member(self, workspace_id: str, member_id: str) -> bool:
        with self._connect() as connection:
            self._retain_workspace_admin(connection, workspace_id, member_id)
            return connection.execute(
                "DELETE FROM kb.workspace_user WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).rowcount > 0

    def add_workspace_org(self, workspace_id: str, *, org_id: str, role: str = "viewer") -> dict:
        self._validate_workspace_role(role, org=True)
        with self._connect() as connection:
            member = connection.execute(
                "SELECT id FROM kb.workspace_org WHERE workspace_id = %s AND org_id = %s",
                (workspace_id, org_id),
            ).fetchone()
            if member is None:
                member_id = _id()
                connection.execute(
                    "INSERT INTO kb.workspace_org (id, workspace_id, org_id, role) VALUES (%s, %s, %s, %s)",
                    (member_id, workspace_id, org_id, role),
                )
            else:
                member_id = member["id"]
                connection.execute("UPDATE kb.workspace_org SET role = %s WHERE id = %s", (role, member_id))
            return self._record(connection.execute("SELECT * FROM kb.workspace_org WHERE id = %s", (member_id,)).fetchone())

    def update_workspace_org(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role, org=True)
        with self._connect() as connection:
            connection.execute(
                "UPDATE kb.workspace_org SET role = %s WHERE workspace_id = %s AND id = %s",
                (role, workspace_id, member_id),
            )
            return self._record(connection.execute(
                "SELECT * FROM kb.workspace_org WHERE workspace_id = %s AND id = %s", (workspace_id, member_id),
            ).fetchone())

    def delete_workspace_org(self, workspace_id: str, member_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "DELETE FROM kb.workspace_org WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).rowcount > 0

    @staticmethod
    def _validate_workspace_role(role: str, *, org: bool = False) -> None:
        allowed = ("editor", "viewer") if org else ("admin", "editor", "viewer")
        if role not in allowed:
            raise ValueError("Invalid workspace role")

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

    def list_workspace_users(self, workspace_id: str, *, org_id: str | None = None,
                             query: str = "", page: int = 1, page_size: int = 20) -> dict:
        scope = """
            FROM kb.users u JOIN active_orgs o ON o.id = u.org_id
            WHERE u.deleted_at IS NULL AND LOWER(u.name) LIKE LOWER(%s) ESCAPE '!'
        """
        pattern = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        params = (workspace_id, f"%{pattern}%")
        if org_id is not None:
            scope += " AND u.org_id = %s"
            params += (org_id,)
        with self._connect() as connection:
            total = connection.execute(
                self._workspace_active_orgs_cte() + "SELECT count(*) AS total " + scope,
                params,
            ).fetchone()["total"]
            rows = connection.execute(
                self._workspace_active_orgs_cte()
                + "SELECT u.id, u.org_id, u.name " + scope
                + " ORDER BY u.name, u.id LIMIT %s OFFSET %s",
                params + (page_size, (page - 1) * page_size),
            ).fetchall()
        return {"users": [self._record(row) for row in rows], "total": total,
                "page": page, "page_size": page_size}
