from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4
from types import SimpleNamespace

import psycopg
import pytest

from kb_api.api.dao import apps as apps_dao
from kb_api.api.dao.files import FilesDAO


def test_create_app_rolls_back_when_root_org_insert_fails(system, monkeypatch):
    dao = system["dao"]
    existing_app, existing_org = dao.create_app("Existing", "existing")
    app_id = str(uuid4())
    identifiers = iter((app_id, existing_org["id"]))
    monkeypatch.setattr(apps_dao, "_id", lambda: next(identifiers))

    with pytest.raises(psycopg.errors.UniqueViolation):
        dao.create_app("Rollback", "rollback")

    assert dao.get_app(app_id) is None
    assert dao.get_app_by_business_id("rollback") is None
    assert dao.get_app(existing_app["id"]) == existing_app
    assert dao.get_org(existing_org["id"]) == existing_org
    with dao._connect() as connection:
        assert connection.execute("SELECT count(*) AS count FROM kb.apps").fetchone()["count"] == 1
        assert connection.execute("SELECT count(*) AS count FROM kb.orgs").fetchone()["count"] == 1


def test_create_workspace_rolls_back_when_creator_grant_fails(system):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    existing = dao.create_workspace(app["id"], "Existing", creator_id=system["admin"]["id"])
    members = dao.list_workspace_members(existing["id"])

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        dao.create_workspace(app["id"], "Rollback", creator_id=str(uuid4()))

    assert dao.list_workspaces(app["id"]) == [existing]
    assert dao.list_workspace_members(existing["id"]) == members
    with dao._connect() as connection:
        assert connection.execute("SELECT count(*) AS count FROM kb.workspace_user").fetchone()["count"] == 1


def test_app_creation_rolls_back_when_vector_initialization_fails(system):
    dao = system["dao"]

    def initialize(app_id):
        raise RuntimeError("Vector initialization failed")

    system["client"].app.state.vector = SimpleNamespace(ensure_app_collection=initialize)
    with pytest.raises(RuntimeError, match="Vector initialization failed"):
        system["client"].post(
            "/api/v1/apps", json={"name": "Rollback", "app_id": "rollback"}, headers=system["headers"],
        )
    assert dao.get_app_by_business_id("rollback") is None
    assert dao.list_orgs(None) == []


def test_concurrent_org_grants_keep_unique_membership(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies")
    roles = ["editor", "viewer"] * 4
    ready = Barrier(len(roles))

    def grant(role):
        ready.wait(timeout=10)
        try:
            return dao.add_workspace_org(workspace["id"], org_id=org["id"], role=role)
        except psycopg.errors.UniqueViolation:
            return None

    with ThreadPoolExecutor(max_workers=len(roles)) as executor:
        futures = [executor.submit(grant, role) for role in roles]
        results = [future.result(timeout=15) for future in futures]

    successful = [member for member in results if member is not None]
    assert successful
    assert len({member["id"] for member in successful}) == 1
    for member, role in zip(results, roles):
        if member is None:
            continue
        assert member["workspace_id"] == workspace["id"]
        assert member["org_id"] == org["id"]
        assert member["role"] == role
    members = dao.list_workspace_members(workspace["id"])
    assert len(members) == 1
    assert members[0]["id"] == successful[0]["id"]
    assert members[0]["role"] in roles


def test_workspace_user_search_keeps_literal_characters_and_pagination(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies")
    names = ["a%name", "b_name", "c!name", "delta", "echo"]
    for name in names:
        dao.create_user(org_id=org["id"], name=name, password_hash=None)

    for query, expected in (("%", "a%name"), ("_", "b_name"), ("!", "c!name"), ("DEL", "delta")):
        result = dao.list_workspace_users(workspace["id"], query=query)
        assert result["total"] == 1
        assert [user["name"] for user in result["users"]] == [expected]

    result = dao.list_workspace_users(workspace["id"], page=2, page_size=2)
    assert result["total"] == 5
    assert [user["name"] for user in result["users"]] == names[2:4]
    assert dao.list_workspace_users(workspace["id"], page=4, page_size=2)["users"] == []


def test_concurrent_file_updates_preserve_independent_fields(system, monkeypatch):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies")
    record = dao.create_file(
        workspace_id=workspace["id"], filename="original.txt", status="uploaded",
        s3_url="s3://kb/original-key", size_bytes=42, created_by=system["admin"]["id"],
    )
    connect = dao._connect
    application_name = f"file_update_{uuid4().hex}"
    ready = Barrier(2)

    def worker_connection():
        connection = connect()
        connection.execute("SELECT set_config('application_name', %s, true)", (application_name,))
        connection.execute("SET LOCAL lock_timeout = '10s'")
        connection.execute("SET LOCAL statement_timeout = '15s'")
        return connection

    def update(values):
        ready.wait(timeout=10)
        return dao.update_file(record["id"], **values)

    with ThreadPoolExecutor(max_workers=2) as executor:
        with connect() as blocker, connect() as observer:
            observer.autocommit = True
            blocker.execute("SELECT id FROM kb.files WHERE id = %s FOR UPDATE", (record["id"],)).fetchone()
            monkeypatch.setattr(dao, "_connect", worker_connection)
            futures = [
                executor.submit(update, {"filename": "renamed.txt"}),
                executor.submit(update, {"status": "indexed"}),
            ]
            deadline = monotonic() + 5
            while True:
                waiting = observer.execute(
                    "SELECT count(*) AS count FROM pg_stat_activity "
                    "WHERE datname = current_database() AND application_name = %s "
                    "AND wait_event_type = 'Lock'",
                    (application_name,),
                ).fetchone()["count"]
                if waiting == 2:
                    break
                assert monotonic() < deadline, "Both file updates must reach the held database row lock"
                sleep(0.01)
        results = [future.result(timeout=15) for future in futures]

    assert results[0]["filename"] == "renamed.txt"
    assert results[1]["status"] == "indexed"
    updated = dao.get_file(record["id"])
    assert updated["filename"] == "renamed.txt"
    assert updated["status"] == "indexed"
    for field in ("id", "workspace_id", "s3_url", "size_bytes", "created_by"):
        assert updated[field] == record[field]


def test_partial_org_and_user_updates_preserve_other_fields(system):
    dao = system["dao"]
    app, root = dao.create_app("Acme", "acme")
    org = dao.create_org(app["id"], root["id"], "Department")
    user = dao.create_user(org_id=org["id"], name="alice", password_hash="old-hash")
    disabled_at = "2026-09-29T00:00:00+00:00"

    dao.update_org(org["id"], deleted_at=disabled_at)
    renamed = dao.update_org(org["id"], name="Renamed")
    assert renamed["parent_id"] == root["id"]
    assert renamed["deleted_at"] is not None
    restored = dao.update_org(org["id"], deleted_at=None)
    assert restored["name"] == "Renamed"
    assert restored["deleted_at"] is None

    dao.update_user(user["id"], deleted_at=disabled_at)
    changed = dao.update_user(user["id"], password_hash="new-hash")
    assert "password_hash" not in changed
    assert changed["org_id"] == org["id"]
    assert changed["role"] == "member"
    assert changed["deleted_at"] is not None
    restored_user = dao.update_user(user["id"], deleted_at=None)
    assert restored_user["deleted_at"] is None
    assert dao.get_user(user["id"])["password_hash"] == "new-hash"
    promoted = dao.update_user(user["id"], org_id=None, role="owner")
    assert promoted["org_id"] is None
    assert promoted["role"] == "owner"


def test_file_error_text_is_decoded():
    record = FilesDAO._record({"filename": "policy.txt", "error": '{"error": "解析失败", "service": "mineru", "retryable": true}'})
    assert record["error"] == {"error": "解析失败", "service": "mineru", "retryable": True}


def test_partial_file_update_can_clear_error(system):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies")
    record = dao.create_file(
        workspace_id=workspace["id"], filename="policy.txt", status="failed",
        error={"error": "Parse failed"}, s3_url="s3://kb/policy-key", size_bytes=42,
    )
    assert record["error"] == {"error": "Parse failed"}
    assert dao.get_file(record["id"])["error"] == record["error"]
    assert dao.list_workspace_files(workspace["id"])[0]["error"] == record["error"]

    updated = dao.update_file(record["id"], error=None, status="indexed")
    assert updated["error"] is None
    assert updated["status"] == "indexed"
    for field in ("filename", "workspace_id", "s3_url", "size_bytes"):
        assert updated[field] == record[field]


def test_update_missing_records_returns_none(system):
    dao = system["dao"]
    missing_id = str(uuid4())
    assert dao.update_org(missing_id, name="Missing") is None
    assert dao.update_user(missing_id, role="member") is None
    assert dao.update_file(missing_id, status="indexed") is None
