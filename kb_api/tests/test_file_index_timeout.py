from datetime import datetime, timedelta, timezone

from kb_api.tests.helpers import upload_file


def _indexing_file(system, name):
    dao = system["dao"]
    app, _ = dao.create_app(name, name.lower())
    workspace = dao.create_workspace(app["id"], "Documents")
    record = dao.create_file(workspace_id=workspace["id"], filename="slow.txt", status="indexing")
    task_id = "8e1a93ec-48e1-452e-a165-ec13e3110ab6"
    dao.set_file_index_task(record["id"], task_id=task_id, token_hash="token-hash")
    return record, task_id


def test_index_task_records_start_without_exposing_internal_timestamp(system):
    record, _ = _indexing_file(system, "Acme")

    with system["dao"]._connect() as connection:
        started_at = connection.execute(
            "SELECT indexing_started_at FROM files WHERE id = %s", (record["id"],),
        ).fetchone()["indexing_started_at"]

    assert started_at is not None
    assert "indexing_started_at" not in system["dao"].get_file(record["id"])


def test_expired_indexing_file_fails_and_late_result_cannot_revive_it(system):
    dao = system["dao"]
    record, task_id = _indexing_file(system, "Acme")
    now = datetime.now(timezone.utc)
    with dao._connect() as connection:
        connection.execute(
            "UPDATE files SET indexing_started_at = %s WHERE id = %s",
            (now - timedelta(minutes=20), record["id"]),
        )

    assert dao.expire_indexing_files(now - timedelta(minutes=15)) == 1
    assert dao.get_file(record["id"])["status"] == "failed"
    assert dao.get_file(record["id"])["error"] == "处理异常"
    assert dao.apply_file_result(
        record["id"], task_id=task_id, token_hash="token-hash",
        expected_status="indexing", status="indexed", error=None, indexed_at=now.isoformat(),
    ) is False


def test_recent_indexing_file_is_not_expired(system):
    dao = system["dao"]
    record, _ = _indexing_file(system, "Acme")

    assert dao.expire_indexing_files(datetime.now(timezone.utc) - timedelta(minutes=15)) == 0
    assert dao.get_file(record["id"])["status"] == "indexing"


def test_timed_out_file_can_retry_and_only_new_task_can_complete(system):
    dao = system["dao"]
    app = system["client"].post(
        "/api/v1/apps", json={"name": "Retry", "app_id": "retry"}, headers=system["headers"],
    ).json()["app"]
    workspace = system["client"].post(
        f"/api/v1/apps/{app['app_id']}/workspaces", json={"name": "Documents"}, headers=system["headers"],
    ).json()["workspace"]
    record = upload_file(system, workspace_id=workspace["id"], filename="retry.txt")
    old_task = dict(system["queue"].messages[-1][1])
    now = datetime.now(timezone.utc)
    with dao._connect() as connection:
        connection.execute(
            "UPDATE files SET indexing_started_at = %s WHERE id = %s",
            (now - timedelta(minutes=20), record["id"]),
        )

    assert dao.expire_indexing_files(now - timedelta(minutes=15)) == 1
    assert dao.get_file(record["id"])["status"] == "failed"

    response = system["client"].post(
        f"/api/v1/workspaces/{workspace['id']}/files/{record['id']}/index",
        json={"s3_url": record["s3_url"], "filename": record["filename"], "content_type": record["mime_type"]},
        headers=system["headers"],
    )
    assert response.status_code == 202, response.text
    assert response.json()["id"] == record["id"]
    assert response.json()["s3_url"] == record["s3_url"]
    assert response.json()["status"] == "indexing"
    assert response.json()["error"] is None
    new_task = system["queue"].messages[-1][1]
    assert len(system["queue"].messages) == 2
    assert new_task["task_id"] != old_task["task_id"]

    old_result = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "index", "file_id": record["id"], "task_id": old_task["task_id"],
              "callback_token": old_task["callback_token"], "status": "indexed"},
    )
    assert old_result.status_code == 401
    assert dao.get_file(record["id"])["status"] == "indexing"

    new_result = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "index", "file_id": record["id"], "task_id": new_task["task_id"],
              "callback_token": new_task["callback_token"], "status": "indexed"},
    )
    assert new_result.status_code == 204, new_result.text
    assert dao.get_file(record["id"])["status"] == "indexed"
