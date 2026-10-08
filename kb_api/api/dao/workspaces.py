from __future__ import annotations

import uuid

from .base import BaseDAO, _id
from .orgs import collect_org_tree


class WorkspacesDAO(BaseDAO):
    def create_workspace(self, app_id: str, name: str, creator_id: str | None = None) -> dict:
        with self._connect() as connection:
            workspace_id = _id()
            connection.execute(
                "INSERT INTO workspaces (id, app_id, name, created_by, created_at, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (workspace_id, app_id, name, creator_id),
            )
            if creator_id is not None:
                connection.execute(
                    "INSERT INTO workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, 'admin')",
                    (_id(), workspace_id, creator_id),
                )
            workspace = connection.execute("SELECT * FROM workspaces WHERE id = %s", (workspace_id,)).fetchone()
            return self._record(workspace)

    def get_workspace(self, workspace_id: str) -> dict | None:
        return self._one("SELECT * FROM workspaces WHERE id = %s", (workspace_id,))

    def list_workspaces(self, app_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workspaces WHERE app_id = %s ORDER BY created_at, id",
                (app_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def update_workspace(self, workspace_id: str, name: str) -> dict | None:
        return self._write_one(
            "UPDATE workspaces SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (name, workspace_id), "SELECT * FROM workspaces WHERE id = %s", (workspace_id,),
        )

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._connect() as connection:
            workspace = connection.execute("SELECT id FROM workspaces WHERE id = %s", (workspace_id,)).fetchone()
            if not workspace:
                return False
            if connection.execute(
                "SELECT id FROM files WHERE workspace_id = %s AND deleted_at IS NULL",
                (workspace_id,),
            ).fetchone():
                raise ValueError("Workspace contains files")
            connection.execute("DELETE FROM workspace_user WHERE workspace_id = %s", (workspace_id,))
            connection.execute("DELETE FROM workspace_org WHERE workspace_id = %s", (workspace_id,))
            connection.execute("DELETE FROM files WHERE workspace_id = %s", (workspace_id,))
            return connection.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,)).rowcount > 0

    def list_workspace_members(self, workspace_id: str) -> list[dict]:
        with self._connect() as connection:
            users = connection.execute(
                """
                SELECT m.id, m.workspace_id, 'user' AS type, m.user_id,
                       u.org_id, u.name, m.role
                FROM workspace_user m JOIN users u ON u.id = m.user_id
                WHERE m.workspace_id = %s
                """,
                (workspace_id,),
            ).fetchall()
            orgs = connection.execute(
                """
                SELECT m.id, m.workspace_id, 'org' AS type, NULL AS user_id,
                       m.org_id, o.name, m.role
                FROM workspace_org m JOIN orgs o ON o.id = m.org_id
                WHERE m.workspace_id = %s
                """,
                (workspace_id,),
            ).fetchall()
        members = [self._record(row) for row in [*users, *orgs]]
        return sorted(members, key=lambda member: (member["type"], str(member["id"])))

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
                "SELECT id FROM workspace_user WHERE workspace_id = %s AND user_id = %s",
                (workspace_id, user_id),
            ).fetchone()
            if role != "admin":
                if member is not None:
                    self._retain_workspace_admin(connection, workspace_id, str(member["id"]))
            if member is None:
                member_id = _id()
                connection.execute(
                    "INSERT INTO workspace_user (id, workspace_id, user_id, role) VALUES (%s, %s, %s, %s)",
                    (member_id, workspace_id, user_id, role),
                )
            else:
                member_id = member["id"]
                connection.execute("UPDATE workspace_user SET role = %s WHERE id = %s", (role, member_id))
            return self._record(connection.execute("SELECT * FROM workspace_user WHERE id = %s", (member_id,)).fetchone())

    def update_workspace_member(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role)
        with self._connect() as connection:
            if role != "admin":
                self._retain_workspace_admin(connection, workspace_id, member_id)
            connection.execute(
                "UPDATE workspace_user SET role = %s WHERE workspace_id = %s AND id = %s",
                (role, workspace_id, member_id),
            )
            return self._record(connection.execute(
                "SELECT * FROM workspace_user WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).fetchone())

    def delete_workspace_member(self, workspace_id: str, member_id: str) -> bool:
        with self._connect() as connection:
            self._retain_workspace_admin(connection, workspace_id, member_id)
            return connection.execute(
                "DELETE FROM workspace_user WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).rowcount > 0

    def add_workspace_org(self, workspace_id: str, *, org_id: str, role: str = "viewer") -> dict:
        self._validate_workspace_role(role, org=True)
        with self._connect() as connection:
            member = connection.execute(
                "SELECT id FROM workspace_org WHERE workspace_id = %s AND org_id = %s",
                (workspace_id, org_id),
            ).fetchone()
            if member is None:
                member_id = _id()
                connection.execute(
                    "INSERT INTO workspace_org (id, workspace_id, org_id, role) VALUES (%s, %s, %s, %s)",
                    (member_id, workspace_id, org_id, role),
                )
            else:
                member_id = member["id"]
                connection.execute("UPDATE workspace_org SET role = %s WHERE id = %s", (role, member_id))
            return self._record(connection.execute("SELECT * FROM workspace_org WHERE id = %s", (member_id,)).fetchone())

    def update_workspace_org(self, workspace_id: str, member_id: str, *, role: str) -> dict | None:
        self._validate_workspace_role(role, org=True)
        with self._connect() as connection:
            connection.execute(
                "UPDATE workspace_org SET role = %s WHERE workspace_id = %s AND id = %s",
                (role, workspace_id, member_id),
            )
            return self._record(connection.execute(
                "SELECT * FROM workspace_org WHERE workspace_id = %s AND id = %s", (workspace_id, member_id),
            ).fetchone())

    def delete_workspace_org(self, workspace_id: str, member_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "DELETE FROM workspace_org WHERE workspace_id = %s AND id = %s",
                (workspace_id, member_id),
            ).rowcount > 0

    @staticmethod
    def _validate_workspace_role(role: str, *, org: bool = False) -> None:
        allowed = ("editor", "viewer") if org else ("admin", "editor", "viewer")
        if role not in allowed:
            raise ValueError("Invalid workspace role")

    @staticmethod
    def _workspace_active_org_ids(connection, workspace_id: str) -> set[str]:
        workspace = connection.execute(
            "SELECT app_id FROM workspaces WHERE id = %s", (workspace_id,),
        ).fetchone()
        if workspace is None:
            return set()
        rows = connection.execute(
            "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
            (workspace["app_id"],),
        ).fetchall()
        return {str(row["id"]) for row in collect_org_tree(rows)}

    def _retain_workspace_admin(self, connection, workspace_id: str, member_id: str) -> None:
        active_org_ids = self._workspace_active_org_ids(connection, workspace_id)
        admins = connection.execute(
            """
            SELECT m.id, u.org_id, u.role, u.deleted_at
            FROM workspace_user m JOIN users u ON u.id = m.user_id
            WHERE m.workspace_id = %s AND m.role = 'admin'
            """,
            (workspace_id,),
        ).fetchall()
        admins = [
            admin for admin in admins
            if admin["deleted_at"] is None
            and (
                (admin["role"] == "owner" and admin["org_id"] is None)
                or str(admin["org_id"]) in active_org_ids
            )
        ]
        if len(admins) == 1 and uuid.UUID(str(admins[0]["id"])) == uuid.UUID(str(member_id)):
            raise ValueError("Workspace must retain an administrator")

    def get_workspace_role(self, user: dict, workspace_id: str) -> str | None:
        if not user.get("id") or user.get("deleted_at") is not None:
            return None
        with self._connect() as connection:
            current_user = connection.execute(
                "SELECT id, org_id, role, deleted_at FROM users WHERE id = %s", (user["id"],),
            ).fetchone()
            if current_user is None or current_user["deleted_at"] is not None:
                return None
            active_org_ids = self._workspace_active_org_ids(connection, workspace_id)
            is_owner = current_user["role"] == "owner" and current_user["org_id"] is None
            if not is_owner and str(current_user["org_id"]) not in active_org_ids:
                return None
            personal = connection.execute(
                "SELECT role FROM workspace_user WHERE workspace_id = %s AND user_id = %s",
                (workspace_id, current_user["id"]),
            ).fetchone()
            if personal is not None:
                return personal["role"]
            if current_user["org_id"] is None:
                return None
            department = connection.execute(
                "SELECT role FROM workspace_org WHERE workspace_id = %s AND org_id = %s",
                (workspace_id, current_user["org_id"]),
            ).fetchone()
            return department["role"] if department is not None else None

    def has_workspace_access(self, user: dict, workspace_id: str) -> bool:
        return self.get_workspace_role(user, workspace_id) is not None

    def list_workspace_users(self, workspace_id: str, *, org_id: str | None = None,
                             query: str = "", page: int = 1, page_size: int = 20) -> dict:
        pattern = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        with self._connect() as connection:
            active_org_ids = self._workspace_active_org_ids(connection, workspace_id)
            if org_id is not None:
                active_org_ids &= {org_id}
            if not active_org_ids:
                return {"users": [], "total": 0, "page": page, "page_size": page_size}
            active_org_ids = sorted(active_org_ids)
            placeholders = ", ".join(["%s"] * len(active_org_ids))
            scope = (
                f"FROM users WHERE org_id IN ({placeholders}) "
                "AND deleted_at IS NULL AND LOWER(name) LIKE LOWER(%s) ESCAPE '!'"
            )
            params = (*active_org_ids, f"%{pattern}%")
            total = connection.execute(
                "SELECT count(*) AS total " + scope,
                params,
            ).fetchone()["total"]
            rows = connection.execute(
                "SELECT id, org_id, name " + scope + " ORDER BY name, id LIMIT %s OFFSET %s",
                params + (page_size, (page - 1) * page_size),
            ).fetchall()
        return {"users": [self._record(row) for row in rows], "total": total,
                "page": page, "page_size": page_size}
