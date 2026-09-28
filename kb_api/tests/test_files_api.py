from kb_api.queue import INDEX_TASK_QUEUE
from kb_api.tests.helpers import upload_file


def _app(system):
    result = system["client"].post(
        "/api/v1/apps", json={"name": "Documents", "app_id": "documents"}, headers=system["headers"]
    )
    return result.json()["app"]


def _workspace(system, app, name):
    result = system["client"].post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": name}, headers=system["headers"]
    )
    assert result.status_code == 201, result.text
    return result.json()["workspace"]


def test_upload_stores_file_record_and_publishes_index_contract(system):
    app = _app(system)
    workspace = _workspace(system, app, "Documents")
    record = upload_file(system, workspace_id=workspace["id"])
    assert record["workspace_id"] == workspace["id"]
    assert "org_id" not in record
    assert "node_id" not in record
    assert record["filename"] == "guide.txt"
    assert record["status"] == "indexing"
    assert record["s3_url"].startswith("s3://kb/uploads/")
    assert record["object_key"].startswith(f"uploads/{app['id']}/{workspace['id']}/{record['id']}/")
    assert system["storage"].objects[record["object_key"]] == b"hello"

    queue_name, message = system["queue"].messages[-1]
    assert queue_name == INDEX_TASK_QUEUE == "kb.index.tasks"
    assert message == {
        "operation": "index",
        "app_id": "documents",
        "workspace_id": workspace["id"],
        "file_id": record["id"],
        "s3_url": record["s3_url"],
        "filename": "guide.txt",
    }
    assert system["client"].get(f"/api/v1/workspaces/{workspace['id']}/files", headers=system["headers"]).json()["files"] == [record]


def test_update_reuses_file_id_and_delete_publishes_delete(system):
    app = _app(system)
    workspace = _workspace(system, app, "Documents")
    created = upload_file(system, workspace_id=workspace["id"], filename="v1.txt", data=b"one")
    updated = upload_file(system, workspace_id=workspace["id"], file_id=created["id"], filename="v2.txt", data=b"two")
    assert updated["id"] == created["id"]
    assert updated["filename"] == "v2.txt"
    assert updated["object_key"] != created["object_key"]
    assert system["queue"].messages[-1][1]["operation"] == "index"

    deleted = system["client"].delete(f"/api/v1/workspaces/{workspace['id']}/files/{created['id']}", headers=system["headers"])
    assert deleted.status_code == 202
    assert deleted.json()["status"] == "deleting"
    queue_name, message = system["queue"].messages[-1]
    assert queue_name == "kb.index.tasks"
    assert message["operation"] == "delete"
    assert message["workspace_id"] == workspace["id"]
    assert message["file_id"] == created["id"]


def test_file_list_is_scoped_to_workspace(system):
    app = _app(system)
    first = _workspace(system, app, "First")
    second = _workspace(system, app, "Second")
    first_file = upload_file(system, workspace_id=first["id"], filename="first.txt", data=b"first")
    second_file = upload_file(system, workspace_id=second["id"], filename="second.txt", data=b"second")

    files = system["client"].get(
        f"/api/v1/workspaces/{second['id']}/files", headers=system["headers"]
    ).json()["files"]

    assert [record["id"] for record in files] == [second_file["id"]]
    assert first_file["id"] not in {record["id"] for record in files}
