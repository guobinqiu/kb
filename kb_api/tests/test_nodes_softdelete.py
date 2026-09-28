from kb_api.auth import hash_password


def test_disabled_branch_hides_users_without_hiding_workspace_files(system):
    client = system["client"]
    created = client.post("/api/v1/apps", json={"app_id": "acme", "name": "Acme"}, headers=system["headers"]).json()
    org = created["org"]
    branch = client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Branch"}, headers=system["headers"]).json()
    user = system["repository"].create_user(
        org_id=branch["id"], name="branch", password_hash=hash_password("password-123"),
    )
    workspace = client.post(
        f"/api/v1/apps/{created['app']['id']}/workspaces", json={"name": "Shared"}, headers=system["headers"]
    ).json()["workspace"]
    file = system["repository"].create_file(workspace_id=workspace["id"], filename="x.txt")
    token = client.post("/api/v1/auth/login", json={"name": "branch", "password": "password-123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.delete(f"/api/v1/orgs/{branch['id']}", headers=system["headers"]).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/login", json={"name": "branch", "password": "password-123"}).json()["error"] == "Account disabled"
    assert user["id"] not in {item["id"] for item in client.get("/api/v1/users", headers=system["headers"]).json()["users"]}
    assert file["id"] in {item["id"] for item in client.get(f"/api/v1/workspaces/{workspace['id']}/files", headers=system["headers"]).json()["files"]}
    assert branch["id"] not in system["repository"].app_org_ids(org["app_id"])
    search_headers = system["headers"] | {"X-App-Id": created["app"]["app_id"]}
    assert client.post("/api/v1/rag/search", json={"query": "hello", "workspace_ids": [workspace["id"]]}, headers=search_headers).status_code == 200
    disabled = client.get("/api/v1/orgs", params={"include_disabled": True}, headers=system["headers"]).json()["orgs"]
    assert {org["id"], branch["id"]}.issubset({org["id"] for org in disabled})
    assert client.put(f"/api/v1/orgs/{branch['id']}", json={"deleted_at": None}, headers=system["headers"]).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_org_move_rejects_cross_app_and_cycle(system):
    client = system["client"]
    a = client.post("/api/v1/apps", json={"app_id": "aaa", "name": "A"}, headers=system["headers"]).json()["org"]
    b = client.post("/api/v1/apps", json={"app_id": "bbb", "name": "B"}, headers=system["headers"]).json()["org"]
    child = client.post("/api/v1/orgs", json={"parent_id": a["id"], "name": "Child"}, headers=system["headers"]).json()
    assert client.put(f"/api/v1/orgs/{child['id']}", json={"parent_id": b["id"]}, headers=system["headers"]).status_code == 403
    assert client.put(f"/api/v1/orgs/{a['id']}", json={"parent_id": child["id"]}, headers=system["headers"]).status_code == 409


def test_only_empty_disabled_org_can_be_removed_permanently(system):
    client = system["client"]
    org = client.post("/api/v1/apps", json={"app_id": "acme", "name": "Acme"}, headers=system["headers"]).json()["org"]
    branch = client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Branch"}, headers=system["headers"]).json()
    system["repository"].create_user(org_id=branch["id"], name="employee", password_hash=None)
    assert client.delete(f"/api/v1/orgs/{branch['id']}", headers=system["headers"]).status_code == 204
    assert client.delete(f"/api/v1/orgs/{branch['id']}/permanent", headers=system["headers"]).status_code == 409
    empty = client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Empty"}, headers=system["headers"]).json()
    assert client.delete(f"/api/v1/orgs/{empty['id']}", headers=system["headers"]).status_code == 204
    assert client.delete(f"/api/v1/orgs/{empty['id']}/permanent", headers=system["headers"]).status_code == 204
    assert system["repository"].get_org(empty["id"]) is None


def test_member_cannot_disable_org_and_top_level_org_cannot_be_disabled(system):
    client = system["client"]
    org = client.post("/api/v1/apps", json={"app_id": "acme", "name": "Acme"}, headers=system["headers"]).json()["org"]
    child = client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Child"}, headers=system["headers"]).json()
    client.post("/api/v1/users", json={"org_id": org["id"], "name": "admin2", "password": "password-123", "role": "admin"}, headers=system["headers"])
    client.post("/api/v1/users", json={"org_id": child["id"], "name": "member", "password": "password-123"}, headers=system["headers"])
    admin_token = client.post("/api/v1/auth/login", json={"name": "admin2", "password": "password-123"}).json()["access_token"]
    member_token = client.post("/api/v1/auth/login", json={"name": "member", "password": "password-123"}).json()["access_token"]
    assert client.delete(f"/api/v1/orgs/{child['id']}", headers={"Authorization": f"Bearer {member_token}"}).status_code == 403
    assert client.delete(f"/api/v1/orgs/{org['id']}", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 409
    assert client.delete(f"/api/v1/orgs/{org['id']}", headers=system["headers"]).status_code == 409
