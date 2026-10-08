import hashlib
from uuid import uuid4

import pytest

from kb_api.api.services.rabbitmq import INDEX_TASK_QUEUE
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
    assert record["s3_url"].startswith(f"s3://kb/uploads/{app['id']}/{workspace['id']}/{record['id']}/")
    assert system["storage"].objects[record["s3_url"]] == b"hello"

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


@pytest.mark.parametrize("filename", ["archive.zip", "photo.png", "document", "report.pdf.exe"])
def test_upload_url_rejects_unsupported_file_type(system, filename):
    workspace = _workspace(system, _app(system), "Documents")
    response = system["client"].post(
        f"/api/v1/workspaces/{workspace['id']}/files/upload-url",
        json={"filename": filename}, headers=system["headers"],
    )
    assert response.status_code == 415, response.text
    assert response.json()["error"].startswith("Unsupported file type")
    assert system["storage"].objects == {}
    assert system["queue"].messages == []


def test_complete_rejects_unsupported_file_type(system):
    app = _app(system)
    workspace = _workspace(system, app, "Documents")
    file_id = str(uuid4())
    s3_url = f"s3://kb/uploads/{app['id']}/{workspace['id']}/{file_id}/source/archive.zip"
    system["storage"].objects[s3_url] = b"archive"
    response = system["client"].post(
        f"/api/v1/workspaces/{workspace['id']}/files/{file_id}/complete",
        json={"filename": "archive.zip", "s3_url": s3_url}, headers=system["headers"],
    )
    assert response.status_code == 415, response.text
    assert system["dao"].get_file(file_id) is None
    assert system["queue"].messages == []


@pytest.mark.parametrize("extension", ["PDF", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md"])
def test_supported_file_types_can_be_uploaded(system, extension):
    workspace = _workspace(system, _app(system), "Documents")
    record = upload_file(system, workspace_id=workspace["id"], filename=f"guide.{extension}")
    assert record["status"] == "indexing"


def test_update_reuses_file_id_and_delete_publishes_delete(system):
    app = _app(system)
    workspace = _workspace(system, app, "Documents")
    created = upload_file(system, workspace_id=workspace["id"], filename="v1.txt", data=b"one")
    updated = upload_file(system, workspace_id=workspace["id"], file_id=created["id"], filename="v2.txt", data=b"two")
    assert updated["id"] == created["id"]
    assert updated["filename"] == "v2.txt"
    assert updated["s3_url"] != created["s3_url"]
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


def _index_result(system, record, status):
    response = system["client"].post(
        "/api/v1/index-results",
        json={
            "operation": "index",
            "file_id": record["id"],
            "status": status,
            "indexed_at": "2026-09-22T12:00:00+00:00" if status == "indexed" else None,
            "error": None if status == "indexed" else {
                "error": "parse failed", "service": "parser", "retryable": True, "traceId": "a" * 32,
            },
        },
        headers=system["service_headers"],
    )
    assert response.status_code == 204, response.text
    return system["dao"].get_file(record["id"])


def test_first_upload_checksum_is_sha256(system):
    workspace = _workspace(system, _app(system), "Documents")
    data = b"first upload contents"

    record = upload_file(system, workspace_id=workspace["id"], data=data)

    assert record["checksum"] == hashlib.sha256(data).hexdigest()
    assert system["dao"].get_file(record["id"])["checksum"] == record["checksum"]
    assert len(system["queue"].messages) == 1


def test_indexed_file_same_content_at_new_upload_path_keeps_indexed_without_task(system):
    workspace = _workspace(system, _app(system), "Documents")
    created = upload_file(system, workspace_id=workspace["id"], filename="v1.txt", data=b"same")
    indexed = _index_result(system, created, "indexed")
    task_count = len(system["queue"].messages)

    updated = upload_file(
        system, workspace_id=workspace["id"], file_id=created["id"], filename="v2.txt", data=b"same",
    )

    assert updated["id"] == created["id"]
    assert updated["s3_url"] != created["s3_url"]
    assert updated["filename"] == "v2.txt"
    assert updated["checksum"] == indexed["checksum"]
    assert updated["status"] == "indexed"
    assert updated["indexed_at"] == indexed["indexed_at"]
    assert updated["error"] is None
    assert len(system["queue"].messages) == task_count
    assert system["dao"].get_file(created["id"]) == updated


def test_indexed_file_changed_content_publishes_new_index_task(system):
    workspace = _workspace(system, _app(system), "Documents")
    created = upload_file(system, workspace_id=workspace["id"], data=b"one")
    _index_result(system, created, "indexed")
    task_count = len(system["queue"].messages)

    updated = upload_file(system, workspace_id=workspace["id"], file_id=created["id"], data=b"two")

    assert updated["id"] == created["id"]
    assert updated["s3_url"] != created["s3_url"]
    assert updated["checksum"] == hashlib.sha256(b"two").hexdigest()
    assert updated["checksum"] != created["checksum"]
    assert updated["status"] == "indexing"
    assert updated["indexed_at"] is None
    assert len(system["queue"].messages) == task_count + 1
    assert system["queue"].messages[-1] == (INDEX_TASK_QUEUE, {
        "operation": "index", "app_id": "documents", "workspace_id": workspace["id"],
        "file_id": updated["id"], "s3_url": updated["s3_url"], "filename": updated["filename"],
    })


def test_failed_file_same_content_can_index_again(system):
    workspace = _workspace(system, _app(system), "Documents")
    created = upload_file(system, workspace_id=workspace["id"], data=b"same")
    failed = _index_result(system, created, "failed")
    assert failed["status"] == "failed"
    assert failed["error"] is not None
    task_count = len(system["queue"].messages)

    response = system["client"].post(
        f"/api/v1/workspaces/{workspace['id']}/files/{created['id']}/complete",
        json={"s3_url": created["s3_url"], "filename": created["filename"]},
        headers=system["headers"],
    )

    assert response.status_code == 202, response.text
    retried = response.json()
    assert retried["checksum"] == created["checksum"]
    assert retried["status"] == "indexing"
    assert retried["indexed_at"] is None
    assert retried["error"] is None
    assert len(system["queue"].messages) == task_count + 1
    assert system["queue"].messages[-1][1]["operation"] == "index"
    assert system["queue"].messages[-1][1]["s3_url"] == created["s3_url"]


def test_indexing_file_complete_same_s3_url_is_idempotent(system):
    workspace = _workspace(system, _app(system), "Documents")
    created = upload_file(system, workspace_id=workspace["id"])
    assert created["status"] == "indexing"
    assert created["indexed_at"] is None
    messages = list(system["queue"].messages)

    response = system["client"].post(
        f"/api/v1/workspaces/{workspace['id']}/files/{created['id']}/complete",
        json={"s3_url": created["s3_url"], "filename": created["filename"]},
        headers=system["headers"],
    )

    assert response.status_code == 202, response.text
    assert response.json() == created
    assert system["dao"].get_file(created["id"]) == created
    assert system["queue"].messages == messages


def test_same_content_with_different_file_id_still_publishes_index_task(system):
    workspace = _workspace(system, _app(system), "Documents")
    first = upload_file(system, workspace_id=workspace["id"], data=b"same")
    _index_result(system, first, "indexed")
    task_count = len(system["queue"].messages)

    second = upload_file(system, workspace_id=workspace["id"], data=b"same")

    assert second["id"] != first["id"]
    assert second["checksum"] == first["checksum"]
    assert second["status"] == "indexing"
    assert second["indexed_at"] is None
    assert len(system["queue"].messages) == task_count + 1
    assert system["queue"].messages[-1][1]["file_id"] == second["id"]
    assert system["queue"].messages[-1][1]["operation"] == "index"


def test_complete_rejects_s3_url_in_other_bucket(system):
    workspace = _workspace(system, _app(system), "Documents")
    base = f"/api/v1/workspaces/{workspace['id']}/files"
    response = system["client"].post(
        f"{base}/upload-url", json={"filename": "guide.txt"}, headers=system["headers"],
    )
    assert response.status_code == 200, response.text
    upload = response.json()
    foreign_url = upload["s3_url"].replace("s3://kb/", "s3://other-bucket/", 1)
    assert foreign_url != upload["s3_url"]
    system["storage"].objects[foreign_url] = b"hello"

    completed = system["client"].post(
        f"{base}/{upload['file_id']}/complete",
        json={"s3_url": foreign_url, "filename": "guide.txt"},
        headers=system["headers"],
    )

    assert completed.status_code == 400, completed.text
    assert system["queue"].messages == []
    assert system["dao"].get_file(upload["file_id"]) is None
