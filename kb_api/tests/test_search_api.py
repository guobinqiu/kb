from types import SimpleNamespace

from fastapi.testclient import TestClient

from kb_api.api.auth import hash_password
from kb_api.rag_search.common.config import SearchConfig
from kb_api.rag_search.service import SearchService


def test_search_accepts_multiple_workspace_ids(system):
    client = system["client"]
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    first = dao.create_workspace(app["id"], "Policies")
    second = dao.create_workspace(app["id"], "Finance")
    user = dao.create_user(
        org_id=org["id"], name="member", password_hash=hash_password("password123"),
    )
    dao.add_workspace_member(first["id"], user_id=user["id"])
    dao.add_workspace_member(second["id"], user_id=user["id"])
    login = client.post("/api/v1/auth/login", json={"name": user["name"], "password": "password123"})
    response = client.post(
        "/api/v1/rag/search",
        headers={"Authorization": f"Bearer {login.json()['access_token']}", "X-App-Id": app["app_id"]},
        json={"query": "policy", "workspace_ids": [second["id"], first["id"]], "file_ids": ["file-1"]},
    )
    assert response.status_code == 200
    request = system["search_service"].requests[-1]["json"]
    assert request["app_id"] == app["app_id"]
    assert request["workspace_ids"] == sorted([first["id"], second["id"]])
    assert request["file_ids"] == ["file-1"]


def test_search_rejects_workspace_outside_membership(system):
    client = system["client"]
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Private")
    user = dao.create_user(
        org_id=org["id"], name="member", password_hash=hash_password("password123"),
    )
    login = client.post("/api/v1/auth/login", json={"name": user["name"], "password": "password123"})
    response = client.post(
        "/api/v1/rag/search",
        headers={"Authorization": f"Bearer {login.json()['access_token']}", "X-App-Id": app["app_id"]},
        json={"query": "policy", "workspace_ids": [workspace["id"]]},
    )
    assert response.status_code == 403
    assert not system["search_service"].requests


def test_legacy_workspace_search_path_is_not_exposed(system):
    assert system["client"].post(
        "/api/v1/workspaces/workspace-1/search", json={"query": "policy"}, headers=system["headers"]
    ).status_code == 404


def test_search_config_reports_active_search_capabilities(system):
    system["search_service"].search_config = SimpleNamespace(mode="hybrid", top_k=5, rerank=True, fetch_k=20)
    system["search_service"].vector = SimpleNamespace(supports_sparse_vector=lambda: True)
    system["search_service"].inference = SimpleNamespace(rerank=object())

    response = system["client"].get("/api/v1/rag/config", headers=system["headers"])

    assert response.status_code == 200
    assert response.json() == {
        "mode": "hybrid",
        "top_k": 5,
        "rerank": True,
        "fetch_k": 20,
        "capabilities": {"sparse_vector": True},
    }


def test_sparse_search_without_sparse_support_returns_bad_request(system):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    application = system["client"].app
    application.state.search_service = SearchService(
        SearchConfig(),
        vector=SimpleNamespace(supports_sparse_vector=lambda: False),
        inference=SimpleNamespace(rerank=None),
    )
    client = TestClient(application, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/rag/search",
        headers=system["headers"] | {"X-App-Id": app["app_id"]},
        json={"query": "policy", "mode": "sparse", "workspace_ids": [workspace["id"]]},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "sparse search is not configured"
    assert response.json()["service"] == "kb_api"
