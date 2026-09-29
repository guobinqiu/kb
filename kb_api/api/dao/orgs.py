from __future__ import annotations

from .base import BaseDAO, _UNSET, _id


def descendants_cte(include_disabled: bool = False) -> str:
    active = "" if include_disabled else " AND deleted_at IS NULL"
    child_active = "" if include_disabled else " AND n.deleted_at IS NULL"
    return f"WITH RECURSIVE descendants AS (SELECT id FROM kb.orgs WHERE id = %s{active} UNION ALL SELECT n.id FROM kb.orgs n JOIN descendants d ON n.parent_id = d.id{child_active})"


class OrgsDAO(BaseDAO):

    def descendant_org_ids(self, org_id: str) -> set[str]:
        if not self.is_active_org(org_id):
            return set()
        with self._connect() as connection:
            rows = connection.execute(descendants_cte() + " SELECT id FROM descendants", (org_id,)).fetchall()
        return {str(row["id"]) for row in rows}

    def subtree_org_ids(self, org_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(descendants_cte(True) + " SELECT id FROM descendants", (org_id,)).fetchall()
        return {str(row["id"]) for row in rows}

    def is_active_org(self, org_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "WITH RECURSIVE ancestors AS (SELECT id, parent_id, deleted_at FROM kb.orgs WHERE id = %s UNION ALL SELECT n.id, n.parent_id, n.deleted_at FROM kb.orgs n JOIN ancestors a ON n.id = a.parent_id) SELECT COUNT(*) AS total, COUNT(deleted_at) AS disabled FROM ancestors",
                (org_id,),
            ).fetchone()
        return row["total"] > 0 and row["disabled"] == 0

    def app_org_ids(self, app_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "WITH RECURSIVE active AS (SELECT id FROM kb.orgs WHERE app_id = %s AND parent_id IS NULL AND deleted_at IS NULL UNION ALL SELECT n.id FROM kb.orgs n JOIN active a ON n.parent_id = a.id WHERE n.deleted_at IS NULL) SELECT id FROM active",
                (app_id,),
            ).fetchall()
        return {str(row["id"]) for row in rows}

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
        org_id = _id()
        return self._write_one(
            "INSERT INTO kb.orgs (id, app_id, parent_id, name, created_at, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (org_id, app_id, parent_id, name), "SELECT * FROM kb.orgs WHERE id = %s", (org_id,),
        )

    def update_org(self, org_id: str, *, name: str | None = None, parent_id: str | None = None, deleted_at=_UNSET) -> dict | None:
        fields = {}
        if name:
            fields["name"] = name
        if parent_id:
            fields["parent_id"] = parent_id
        if deleted_at is not _UNSET:
            fields["deleted_at"] = deleted_at
        assignments = [f"{field} = %s" for field in fields] + ["updated_at = CURRENT_TIMESTAMP"]
        return self._write_one(
            "UPDATE kb.orgs SET " + ", ".join(assignments) + " WHERE id = %s",
            tuple(fields.values()) + (org_id,), "SELECT * FROM kb.orgs WHERE id = %s", (org_id,),
        )

    def delete_org(self, org_id: str) -> bool:
        return self._execute("UPDATE kb.orgs SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND parent_id IS NOT NULL", (org_id,))

    def purge_org(self, org_id: str) -> bool:
        with self._connect() as connection:
            org = connection.execute(
                "SELECT id FROM kb.orgs WHERE id = %s AND parent_id IS NOT NULL AND deleted_at IS NOT NULL",
                (org_id,),
            ).fetchone()
            if not org:
                return False
            if connection.execute("SELECT id FROM kb.orgs WHERE parent_id = %s", (org_id,)).fetchone():
                return False
            if connection.execute("SELECT id FROM kb.users WHERE org_id = %s", (org_id,)).fetchone():
                return False
            connection.execute("DELETE FROM kb.workspace_org WHERE org_id = %s", (org_id,))
            return connection.execute("DELETE FROM kb.orgs WHERE id = %s", (org_id,)).rowcount > 0
