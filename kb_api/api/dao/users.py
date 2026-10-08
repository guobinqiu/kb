from __future__ import annotations

from .base import BaseDAO, _UNSET, _id
from .orgs import collect_org_tree


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "password_hash"}


class UsersDAO(BaseDAO):
    def create_user(self, *, org_id: str | None, name: str, password_hash: str | None, role: str = "member") -> dict:
        user_id = _id()
        return self._write_one(
            "INSERT INTO users (id, org_id, name, password_hash, role, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (user_id, org_id, name, password_hash, role), "SELECT * FROM users WHERE id = %s", (user_id,),
        )

    def get_user(self, user_id: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE id = %s", (user_id,))

    def get_user_by_name(self, name: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE name = %s", (name,))

    def list_users(self, user_org_id: str | None, include_disabled: bool = False) -> list[dict]:
        active_user = "" if include_disabled else " WHERE u.deleted_at IS NULL"
        with self._connect() as connection:
            if user_org_id is None:
                rows = connection.execute("SELECT u.* FROM users u" + active_user + " ORDER BY u.created_at").fetchall()
            else:
                org = connection.execute("SELECT app_id FROM orgs WHERE id = %s", (user_org_id,)).fetchone()
                if org is None:
                    return []
                org_rows = connection.execute(
                    "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
                    (org["app_id"],),
                ).fetchall()
                org_ids = [
                    str(row["id"])
                    for row in collect_org_tree(
                        org_rows, root_id=user_org_id, include_disabled=include_disabled,
                    )
                ]
                if not org_ids:
                    return []
                placeholders = ", ".join(["%s"] * len(org_ids))
                active_user = "" if include_disabled else " AND deleted_at IS NULL"
                rows = connection.execute(
                    f"SELECT * FROM users WHERE org_id IN ({placeholders}){active_user} ORDER BY created_at",
                    tuple(org_ids),
                ).fetchall()
        return [_public_user(self._record(row)) for row in rows]

    def list_org_users(self, org_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users WHERE org_id = %s AND deleted_at IS NULL ORDER BY created_at, id",
                (org_id,),
            ).fetchall()
        return [_public_user(self._record(row)) for row in rows]

    def update_user(self, user_id: str, *, org_id=_UNSET, password_hash: str | None = None, role: str | None = None, deleted_at=_UNSET) -> dict | None:
        fields = {}
        if org_id is not _UNSET:
            fields["org_id"] = org_id
        if password_hash:
            fields["password_hash"] = password_hash
        if role:
            fields["role"] = role
        if deleted_at is not _UNSET:
            fields["deleted_at"] = deleted_at
        assignments = [f"{field} = %s" for field in fields] + ["updated_at = CURRENT_TIMESTAMP"]
        row = self._write_one(
            "UPDATE users SET " + ", ".join(assignments) + " WHERE id = %s",
            tuple(fields.values()) + (user_id,), "SELECT * FROM users WHERE id = %s", (user_id,),
        )
        return _public_user(row) if row else None

    def delete_user(self, user_id: str) -> bool:
        return self._execute("UPDATE users SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (user_id,))
