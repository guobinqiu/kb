import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kb_api.api.routes.files import router
from kb_api.api.auth import current_user
from kb_api.api.services.rabbitmq import INDEX_TASK_QUEUE
from kb_api.api.rate_limit import require_index_rate_limit, require_rate_limit
from kb_api.tests.helpers import upload_file


class DAO:
    def __init__(self):
        self.workspace = {"id": "workspace-uuid", "app_id": "app-uuid"}
        self.org = {"id": "org-uuid", "app_id": "app-uuid"}
        self.files = {}
        self.index_tasks = {}
        self.allowed = True
        self.workspace_role = "admin"

    def get_workspace(self, workspace_id):
        return self.workspace if workspace_id == self.workspace["id"] else None

    def get_org(self, org_id):
        return self.org if org_id == self.org["id"] else None

    def has_workspace_access(self, user, workspace_id):
        return self.allowed and workspace_id == self.workspace["id"]

    def get_workspace_role(self, user, workspace_id):
        return self.workspace_role if self.has_workspace_access(user, workspace_id) else None

    def list_workspace_files(self, workspace_id):
        return [record for record in self.files.values() if record["workspace_id"] == workspace_id]

    def get_file(self, file_id):
        return self.files.get(file_id)

    def create_file(self, **values):
        self.files[values["id"]] = dict(values)
        return self.files[values["id"]]

    def update_file(self, file_id, **values):
        self.files[file_id].update(values)
        return self.files[file_id]

    def set_file_index_task(self, file_id, *, task_id, token_hash):
        self.index_tasks[file_id] = (task_id, token_hash)

    def apply_file_result(
        self, file_id, *, task_id, token_hash, status, error, indexed_at, deleted=False,
    ):
        if self.index_tasks.get(file_id) != (task_id, token_hash):
            return False
        self.files[file_id].update({
            "status": status,
            "error": error,
            "indexed_at": indexed_at,
            "deleted_at": "deleted" if deleted else None,
        })
        return True

    def get_app(self, app_id):
        return {"id": app_id, "app_id": "business_app"} if app_id == "app-uuid" else None

class Storage:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def presign_put(self, object_key, expires_seconds):
        return f"http://storage/{object_key}"

    def stat(self, s3_url):
        return SimpleNamespace(size=len(self.objects[s3_url]), content_type="text/plain")

    def checksum(self, s3_url):
        return hashlib.sha256(self.objects[s3_url]).hexdigest()

    def object_url(self, object_key):
        return f"s3://kb/{object_key}"

    def delete(self, s3_url):
        self.deleted.append(s3_url)
        self.objects.pop(s3_url, None)


class Queue:
    def __init__(self):
        self.messages = []
        self.error = None

    def publish(self, name, message):
        if self.error:
            raise self.error
        self.messages.append((name, message))


def make_client(role="admin"):
    app = FastAPI()
    app.include_router(router)
    dao = DAO()
    dao.workspace_role = "editor" if role == "member" else "admin"
    storage = Storage()
    queue = Queue()
    app.state.dao = dao
    app.state.storage = storage
    app.state.queue = queue
    app.dependency_overrides[current_user] = lambda: {"id": "user-uuid", "org_id": "org-uuid", "role": role}
    app.dependency_overrides[require_rate_limit] = lambda: None
    app.dependency_overrides[require_index_rate_limit] = lambda: None
    return TestClient(app), dao, storage, queue


def test_workspace_file_lifecycle_uses_workspace_scope_and_index_contract():
    client, dao, storage, queue = make_client()
    base = "/api/v1/workspaces/workspace-uuid/files"
    assert client.get("/api/v1/files").status_code == 404
    assert client.post("/api/v1/files/upload-url", json={"node_id": "node-uuid", "filename": "legacy.txt"}).status_code == 404

    prepared = client.post(f"{base}/upload-url", json={"filename": "guide.txt"})
    assert prepared.status_code == 200, prepared.text
    upload = prepared.json()
    assert upload["s3_url"].startswith(f"s3://kb/uploads/app-uuid/workspace-uuid/{upload['file_id']}/")
    assert "node_id" not in upload
    storage.objects[upload["s3_url"]] = b"hello"

    indexed = client.post(
        f"{base}/{upload['file_id']}/index",
        json={"s3_url": upload["s3_url"], "filename": "guide.txt"},
    )
    assert indexed.status_code == 202, indexed.text
    record = indexed.json()
    assert record["workspace_id"] == "workspace-uuid"
    assert "org_id" not in record
    assert "node_id" not in record
    queue_name, message = queue.messages[-1]
    expected = {
        "operation": "index", "app_id": "business_app", "workspace_id": "workspace-uuid",
        "file_id": upload["file_id"], "s3_url": record["s3_url"], "filename": "guide.txt",
    }
    assert queue_name == INDEX_TASK_QUEUE
    assert message.items() >= expected.items()
    assert message["task_id"]
    assert message["callback_token"]
    assert client.post(
        f"{base}/{upload['file_id']}/complete",
        json={"s3_url": upload["s3_url"], "filename": "guide.txt"},
    ).status_code == 404
    assert client.get(base).json() == {"files": [record]}
    assert client.get(f"{base}/{upload['file_id']}").json() == record

    deleted = client.delete(f"{base}/{upload['file_id']}")
    assert deleted.status_code == 202, deleted.text
    assert deleted.json()["status"] == "deleting"
    message = queue.messages[-1][1]
    expected = {
        "operation": "delete", "app_id": "business_app", "workspace_id": "workspace-uuid",
        "file_id": upload["file_id"], "s3_url": record["s3_url"], "filename": "guide.txt",
    }
    assert message.items() >= expected.items()
    assert message["task_id"]
    assert message["callback_token"]


def test_workspace_file_routes_reject_other_workspace_and_invalid_object_path():
    client, dao, storage, queue = make_client()
    base = "/api/v1/workspaces/workspace-uuid/files"
    response = client.post(f"{base}/upload-url", json={"filename": "guide.txt"})
    assert response.status_code == 200, response.text
    prepared = response.json()
    storage.objects[prepared["s3_url"]] = b"hello"

    wrong_url = prepared["s3_url"].replace("workspace-uuid", "other-workspace")
    invalid = client.post(
        f"{base}/{prepared['file_id']}/index",
        json={"s3_url": wrong_url, "filename": "guide.txt"},
    )
    assert invalid.status_code == 400
    assert queue.messages == []

    dao.allowed = False
    assert client.get(base).status_code == 404
    assert client.post(f"{base}/upload-url", json={"filename": "guide.txt"}).status_code == 404
    assert client.post(
        f"{base}/{prepared['file_id']}/index",
        json={"s3_url": prepared["s3_url"], "filename": "guide.txt"},
    ).status_code == 404


def test_workspace_file_update_keeps_file_id_and_rejects_foreign_file():
    client, dao, storage, queue = make_client()
    base = "/api/v1/workspaces/workspace-uuid/files"
    first = client.post(f"{base}/upload-url", json={"filename": "v1.txt"}).json()
    storage.objects[first["s3_url"]] = b"one"
    created = client.post(
        f"{base}/{first['file_id']}/index",
        json={"s3_url": first["s3_url"], "filename": "v1.txt"},
    ).json()

    replacement = client.post(
        f"{base}/upload-url", json={"file_id": created["id"], "filename": "v2.txt"},
    )
    assert replacement.status_code == 200, replacement.text
    upload = replacement.json()
    assert upload["file_id"] == created["id"]
    assert upload["s3_url"] != created["s3_url"]
    storage.objects[upload["s3_url"]] = b"two"
    updated = client.post(
        f"{base}/{upload['file_id']}/index",
        json={"s3_url": upload["s3_url"], "filename": "v2.txt"},
    )
    assert updated.status_code == 202, updated.text
    assert updated.json()["id"] == created["id"]
    assert updated.json()["workspace_id"] == "workspace-uuid"
    assert updated.json()["filename"] == "v2.txt"
    assert len(queue.messages) == 2

    foreign_base = "/api/v1/workspaces/other-workspace/files"
    dao.workspace = {"id": "other-workspace", "app_id": "app-uuid"}
    assert client.get(f"{foreign_base}/{created['id']}").status_code == 404
    assert client.delete(f"{foreign_base}/{created['id']}").status_code == 404
    assert client.post(
        f"{foreign_base}/upload-url", json={"file_id": created["id"], "filename": "stolen.txt"},
    ).status_code == 404
    assert client.post(
        f"{foreign_base}/{created['id']}/index",
        json={"s3_url": upload["s3_url"], "filename": "v2.txt"},
    ).status_code == 400
    assert len(queue.messages) == 2


def test_index_marks_file_failed_when_index_task_publish_fails():
    client, dao, storage, queue = make_client()
    base = "/api/v1/workspaces/workspace-uuid/files"
    prepared = client.post(f"{base}/upload-url", json={"filename": "guide.txt"}).json()
    storage.objects[prepared["s3_url"]] = b"hello"
    queue.error = RuntimeError("rabbitmq unavailable")

    indexed = client.post(
        f"{base}/{prepared['file_id']}/index",
        json={"s3_url": prepared["s3_url"], "filename": "guide.txt"},
    )

    assert indexed.status_code == 503
    record = dao.get_file(prepared["file_id"])
    assert record["status"] == "failed"
    assert record["indexed_at"] is None
    assert record["error"] == {
        "error": "rabbitmq unavailable",
        "service": "kb_api.queue",
        "retryable": True,
        "traceId": indexed.json()["detail"]["traceId"],
    }


def test_delete_marks_file_delete_failed_when_index_task_publish_fails():
    client, dao, storage, queue = make_client()
    base = "/api/v1/workspaces/workspace-uuid/files"
    prepared = client.post(f"{base}/upload-url", json={"filename": "guide.txt"}).json()
    storage.objects[prepared["s3_url"]] = b"hello"
    created = client.post(
        f"{base}/{prepared['file_id']}/index",
        json={"s3_url": prepared["s3_url"], "filename": "guide.txt"},
    ).json()
    queue.error = RuntimeError("rabbitmq unavailable")

    deleted = client.delete(f"{base}/{created['id']}")

    assert deleted.status_code == 503
    record = dao.get_file(created["id"])
    assert record["status"] == "delete_failed"
    assert record["error"] == {
        "error": "rabbitmq unavailable",
        "service": "kb_api.queue",
        "retryable": True,
        "traceId": deleted.json()["detail"]["traceId"],
    }


def test_upload_helper_uses_workspace_route_without_org_id():
    client, dao, storage, queue = make_client()
    record = upload_file(
        {"client": client, "headers": {}, "storage": storage},
        workspace_id="workspace-uuid",
    )
    assert record["workspace_id"] == "workspace-uuid"
    assert "org_id" not in record
    assert "node_id" not in record
    assert queue.messages[-1][1]["workspace_id"] == "workspace-uuid"


def test_workspace_member_can_upload_and_manage_own_files_only():
    client, dao, storage, queue = make_client(role="member")
    base = "/api/v1/workspaces/workspace-uuid/files"

    assert client.get(base).status_code == 200
    prepared = client.post(f"{base}/upload-url", json={"filename": "guide.txt"})
    assert prepared.status_code == 200, prepared.text
    upload = prepared.json()
    storage.objects[upload["s3_url"]] = b"hello"
    indexed = client.post(
        f"{base}/{upload['file_id']}/index",
        json={"s3_url": upload["s3_url"], "filename": "guide.txt"},
    )
    assert indexed.status_code == 202, indexed.text
    assert indexed.json()["created_by"] == "user-uuid"
    assert client.post(
        f"{base}/upload-url", json={"file_id": upload["file_id"], "filename": "updated.txt"},
    ).status_code == 200

    dao.files["file-uuid"] = {
        "id": "file-uuid",
        "workspace_id": "workspace-uuid",
        "filename": "guide.txt",
        "s3_url": "s3://kb/guide.txt",
        "status": "indexed",
        "created_by": "other-user",
    }
    assert client.post(
        f"{base}/upload-url", json={"file_id": "file-uuid", "filename": "updated.txt"},
    ).status_code == 403
    foreign_url = "s3://kb/uploads/app-uuid/workspace-uuid/file-uuid/other/guide.txt"
    storage.objects[foreign_url] = b"other"
    assert client.post(
        f"{base}/file-uuid/index",
        json={"s3_url": foreign_url, "filename": "guide.txt"},
    ).status_code == 403
    assert client.delete(f"{base}/file-uuid").status_code == 403
    assert client.delete(f"{base}/{upload['file_id']}").status_code == 202
