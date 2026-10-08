from __future__ import annotations

import secrets
from contextlib import nullcontext

from .base import BaseDAO, _id


class AppsDAO(BaseDAO):
    def create_app(self, name: str, app_id: str, api_key: str | None = None, *, connection=None) -> tuple[dict, dict]:
        with (self._connect() if connection is None else nullcontext(connection)) as connection:
            app_record_id, org_id = _id(), _id()
            connection.execute(
                "INSERT INTO apps (id, app_id, name, api_key, created_at, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (app_record_id, app_id, name, api_key or secrets.token_urlsafe(32)),
            )
            connection.execute(
                "INSERT INTO orgs (id, app_id, parent_id, name, created_at, updated_at) VALUES (%s, %s, NULL, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (org_id, app_record_id, name),
            )
            app = connection.execute("SELECT * FROM apps WHERE id = %s", (app_record_id,)).fetchone()
            org = connection.execute("SELECT * FROM orgs WHERE id = %s", (org_id,)).fetchone()
            return self._record(app), self._record(org)

    def list_apps(self, user_org_id: str | None) -> list[dict]:
        with self._connect() as connection:
            if user_org_id is None:
                rows = connection.execute("SELECT * FROM apps ORDER BY created_at").fetchall()
            else:
                rows = connection.execute(
                    "SELECT a.* FROM apps a JOIN orgs o ON o.app_id = a.id WHERE o.id = %s ORDER BY a.created_at",
                    (user_org_id,),
                ).fetchall()
        return [self._record(row) for row in rows]

    def get_app(self, app_id: str) -> dict | None:
        return self._one("SELECT * FROM apps WHERE id = %s", (app_id,))

    def get_app_by_business_id(self, app_id: str) -> dict | None:
        return self._one("SELECT * FROM apps WHERE app_id = %s", (app_id,))

    def get_app_by_api_key(self, api_key: str) -> dict | None:
        return self._one("SELECT * FROM apps WHERE api_key = %s", (api_key,))

    def update_app(self, app_id: str, name: str) -> dict | None:
        return self._write_one(
            "UPDATE apps SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (name, app_id), "SELECT * FROM apps WHERE id = %s", (app_id,),
        )

    def delete_app(self, app_id: str) -> bool:
        with self._connect() as connection:
            if connection.execute("SELECT id FROM workspaces WHERE app_id = %s", (app_id,)).fetchone():
                raise ValueError("App contains workspaces")
            if connection.execute("SELECT id FROM orgs WHERE app_id = %s", (app_id,)).fetchone():
                raise ValueError("App contains orgs")
            return connection.execute("DELETE FROM apps WHERE id = %s", (app_id,)).rowcount > 0

    def has_app_orgs(self, app_id: str) -> bool:
        return self._one("SELECT 1 FROM orgs WHERE app_id = %s", (app_id,)) is not None
