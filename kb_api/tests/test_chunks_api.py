from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kb_api.api.routes.chunks import router
from kb_api.api.auth import current_user


class FakeChunkVector:
    def __init__(self):
        self.calls = []

    @contextmanager
    def app_scope(self, app_id):
        self.calls.append(("scope", app_id))
        yield

    def app_collection_exists(self, app_id):
        self.calls.append(("exists", app_id))
        return True

    def list_chunks(self, *, file_ids, workspace_ids, limit, cursor):
        self.calls.append(("list", file_ids, workspace_ids, limit, cursor))
        return {
            "documents": [{
                "id": "chunk-1",
                "content": "Workspace chunk",
                "metadata": {
                    "file_id": file_ids[0],
                    "filename": "indexed.txt",
                    "chunk_index": 0,
                    "created_at": "2026-09-23T00:00:00Z",
                    "s3_url": "s3://kb/indexed.txt",
                },
            }],
            "next_cursor": "next-page",
            "has_more": True,
        }


class FakeDAO:
    def __init__(self):
        self.workspace = {"id": "workspace-1", "app_id": "app-1"}
        self.allowed = True
        self.files = [
            {"id": "file-1", "filename": "visible.txt", "s3_url": "s3://kb/visible.txt"},
            {"id": "file-2", "filename": "other.txt", "s3_url": "s3://kb/other.txt"},
        ]

    def get_workspace(self, workspace_id):
        return self.workspace if workspace_id == self.workspace["id"] else None

    def has_workspace_access(self, user, workspace_id):
        assert user["id"] == "user-1"
        return self.allowed and workspace_id == self.workspace["id"]

    def get_workspace_role(self, user, workspace_id):
        return "viewer" if self.has_workspace_access(user, workspace_id) else None

    def get_app(self, app_id):
        return {"id": "app-1", "app_id": "acme"} if app_id == "app-1" else None

    def list_workspace_files(self, workspace_id):
        assert workspace_id == self.workspace["id"]
        return self.files


def make_client():
    app = FastAPI()
    app.include_router(router)
    dao = FakeDAO()
    vector = FakeChunkVector()
    app.state.dao = dao
    app.state.search_service = SimpleNamespace(vector=vector)
    app.dependency_overrides[current_user] = lambda: {"id": "user-1", "role": "member"}
    return TestClient(app), dao, vector


def test_workspace_chunks_use_app_collection_and_workspace_filter():
    client, _, vector = make_client()

    response = client.get(
        "/api/v1/workspaces/workspace-1/chunks",
        params={"limit": 10, "cursor": "previous", "file_ids": "file-1"},
    )

    assert response.status_code == 200
    assert vector.calls == [
        ("exists", "acme"),
        ("scope", "acme"),
        ("list", ["file-1"], ["workspace-1"], 10, "previous"),
    ]
    assert response.json() == {
        "chunks": [{
            "id": "chunk-1",
            "file_id": "file-1",
            "filename": "visible.txt",
            "s3_url": "s3://kb/visible.txt",
            "chunk_index": 0,
            "created_at": "2026-09-23T00:00:00Z",
            "content": "Workspace chunk",
        }],
        "next_cursor": "next-page",
        "has_more": True,
    }


def test_workspace_chunks_hide_missing_or_forbidden_workspace():
    client, dao, vector = make_client()

    assert client.get("/api/v1/workspaces/missing/chunks").status_code == 404
    dao.allowed = False
    assert client.get("/api/v1/workspaces/workspace-1/chunks").status_code == 404
    assert vector.calls == []


def test_workspace_chunks_return_empty_without_matching_files():
    client, dao, vector = make_client()
    dao.files = []

    response = client.get("/api/v1/workspaces/workspace-1/chunks")

    assert response.status_code == 200
    assert response.json() == {"chunks": [], "next_cursor": None, "has_more": False}
    assert vector.calls == []


def test_workspace_chunks_reject_file_ids_outside_workspace():
    client, _, vector = make_client()

    response = client.get(
        "/api/v1/workspaces/workspace-1/chunks", params={"file_ids": "other-workspace-file"}
    )

    assert response.status_code == 200
    assert response.json()["chunks"] == []
    assert vector.calls == []


def test_legacy_app_chunks_route_is_removed():
    client, _, _ = make_client()

    assert client.get("/api/v1/apps/app-1/chunks").status_code == 404
