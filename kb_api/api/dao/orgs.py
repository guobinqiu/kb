from __future__ import annotations

from .base import BaseDAO, _UNSET, _id


def collect_org_tree(rows: list[dict], *, root_id: str | None = None,
                     include_disabled: bool = False) -> list[dict]:
    orgs = {str(row["id"]): row for row in rows}
    children: dict[str | None, list[dict]] = {}
    for row in rows:
        parent_id = str(row["parent_id"]) if row["parent_id"] is not None else None
        children.setdefault(parent_id, []).append(row)

    if root_id is None:
        pending = list(children.get(None, []))
    elif root_id in orgs:
        pending = [orgs[root_id]]
    else:
        pending = []
    result = []
    while pending:
        row = pending.pop()
        if not include_disabled and row["deleted_at"] is not None:
            continue
        result.append(row)
        pending.extend(children.get(str(row["id"]), []))
    return sorted(result, key=lambda row: (row["created_at"], str(row["id"])))


class OrgsDAO(BaseDAO):

    def descendant_org_ids(self, org_id: str) -> set[str]:
        with self._connect() as connection:
            org = connection.execute("SELECT app_id FROM orgs WHERE id = %s", (org_id,)).fetchone()
            if org is None:
                return set()
            rows = connection.execute(
                "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
                (org["app_id"],),
            ).fetchall()
        return {str(row["id"]) for row in collect_org_tree(rows, root_id=org_id)}

    def subtree_org_ids(self, org_id: str) -> set[str]:
        with self._connect() as connection:
            org = connection.execute("SELECT app_id FROM orgs WHERE id = %s", (org_id,)).fetchone()
            if org is None:
                return set()
            rows = connection.execute(
                "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
                (org["app_id"],),
            ).fetchall()
        return {
            str(row["id"])
            for row in collect_org_tree(rows, root_id=org_id, include_disabled=True)
        }

    def is_active_org(self, org_id: str) -> bool:
        with self._connect() as connection:
            org = connection.execute("SELECT app_id FROM orgs WHERE id = %s", (org_id,)).fetchone()
            if org is None:
                return False
            rows = connection.execute(
                "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
                (org["app_id"],),
            ).fetchall()
        return org_id in {str(row["id"]) for row in collect_org_tree(rows)}

    def app_org_ids(self, app_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, parent_id, deleted_at, created_at FROM orgs WHERE app_id = %s",
                (app_id,),
            ).fetchall()
        return {str(row["id"]) for row in collect_org_tree(rows)}

    def get_org(self, org_id: str) -> dict | None:
        return self._one("SELECT * FROM orgs WHERE id = %s", (org_id,))

    def list_orgs(self, user_org_id: str | None, include_disabled: bool = False) -> list[dict]:
        if user_org_id is not None:
            selected_org = self.get_org(user_org_id)
            if not selected_org:
                return []
            return self._list_app_orgs(selected_org["app_id"], include_disabled=include_disabled)
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM orgs").fetchall()
        return [self._record(row) for row in collect_org_tree(rows, include_disabled=include_disabled)]

    def list_app_orgs(self, app_id: str) -> list[dict]:
        return self._list_app_orgs(app_id, include_disabled=False)

    def _list_app_orgs(self, app_id: str, *, include_disabled: bool) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM orgs WHERE app_id = %s",
                (app_id,),
            ).fetchall()
        return [self._record(row) for row in collect_org_tree(rows, include_disabled=include_disabled)]

    def create_org(self, app_id: str, parent_id: str, name: str) -> dict:
        org_id = _id()
        return self._write_one(
            "INSERT INTO orgs (id, app_id, parent_id, name, created_at, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (org_id, app_id, parent_id, name), "SELECT * FROM orgs WHERE id = %s", (org_id,),
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
            "UPDATE orgs SET " + ", ".join(assignments) + " WHERE id = %s",
            tuple(fields.values()) + (org_id,), "SELECT * FROM orgs WHERE id = %s", (org_id,),
        )

    def delete_org(self, org_id: str) -> bool:
        return self._execute("UPDATE orgs SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND parent_id IS NOT NULL", (org_id,))
