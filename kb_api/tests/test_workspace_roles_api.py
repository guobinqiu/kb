from kb_api.api.auth import hash_password
from kb_api.tests.helpers import upload_file


def _setup(system):
    repo = system["dao"]
    app, org = repo.create_app("Roles", "roles")
    workspace = repo.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    user = repo.create_user(org_id=org["id"], name="reader", password_hash=hash_password("password123"))
    login = system["client"].post("/api/v1/auth/login", json={"name": "reader", "password": "password123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return app, org, workspace, user, headers


def test_org_grant_personal_override_and_workspace_admin_directory(system):
    _, org, workspace, user, headers = _setup(system)
    client, repo = system["client"], system["dao"]
    base = f"/api/v1/workspaces/{workspace['id']}"
    owner = system["headers"]
    denied = client.post(f"{base}/members", json={"type": "org", "id": org["id"], "role": "admin"}, headers=owner)
    assert denied.status_code == 422
    granted = client.post(f"{base}/members", json={"type": "org", "id": org["id"], "role": "editor"}, headers=owner)
    assert granted.status_code == 201
    org_member = granted.json()["member"]
    preview = client.get(f"{base}/users", params={"org_id": org["id"]}, headers=owner)
    assert [item["id"] for item in preview.json()["users"]] == [user["id"]]
    assert client.get(base, headers=headers).json()["role"] == "editor"
    personal = client.post(f"{base}/members", json={"type": "user", "id": user["id"], "role": "viewer"}, headers=owner)
    assert personal.status_code == 201
    member_id = personal.json()["member"]["id"]
    assert client.get(base, headers=headers).json()["role"] == "viewer"
    assert client.get(f"{base}/orgs", headers=headers).status_code == 403
    assert client.get(f"{base}/users", headers=headers).status_code == 403
    promoted = client.put(f"{base}/members/{member_id}?type=user", json={"role": "admin"}, headers=owner)
    assert promoted.status_code == 200
    directory = client.get(f"{base}/orgs", headers=headers)
    assert directory.status_code == 200
    assert [item["id"] for item in directory.json()["orgs"]] == [org["id"]]
    assert "password_hash" not in client.get(f"{base}/users", headers=headers).json()["users"][0]
    _, outsider_org = repo.create_app("Other", "other")
    outsider = repo.create_user(org_id=outsider_org["id"], name="outsider", password_hash=None)
    for kind, target in [("org", outsider_org), ("user", outsider)]:
        assert client.post(f"{base}/members", json={"type": kind, "id": target["id"], "role": "viewer"}, headers=headers).status_code == 422
    assert client.delete(f"{base}/members/{member_id}?type=user", headers=headers).status_code == 204
    assert client.get(base, headers=headers).json()["role"] == "editor"
    assert client.delete(f"{base}/members/{org_member['id']}?type=org", headers=owner).status_code == 204
    assert client.get(base, headers=headers).status_code == 404


def test_last_workspace_admin_cannot_be_removed_or_demoted(system):
    _, _, workspace, _, _ = _setup(system)
    repo, client = system["dao"], system["client"]
    member = next(item for item in repo.list_workspace_members(workspace["id"]) if item["role"] == "admin")
    url = f"/api/v1/workspaces/{workspace['id']}/members/{member['id']}?type=user"
    assert client.put(url, json={"role": "viewer"}, headers=system["headers"]).status_code == 409
    assert client.delete(url, headers=system["headers"]).status_code == 409


def test_workspace_creator_can_delete_but_other_admin_cannot(system):
    app, org, _, creator, headers = _setup(system)
    dao, client = system["dao"], system["client"]
    dao.update_user(creator["id"], role="admin")
    response = client.post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": "Created"}, headers=headers,
    )
    assert response.status_code == 201, response.text
    workspace = response.json()["workspace"]
    assert workspace["created_by"] == creator["id"]
    other = dao.create_user(org_id=org["id"], name="other-admin", password_hash=hash_password("password123"), role="admin")
    dao.add_workspace_member(workspace["id"], user_id=other["id"], role="admin")
    login = client.post("/api/v1/auth/login", json={"name": other["name"], "password": "password123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = f"/api/v1/workspaces/{workspace['id']}"
    assert client.get(base, headers=other_headers).json()["permissions"]["workspace.delete"] is False
    assert client.delete(base, headers=other_headers).status_code == 403
    assert client.get(base, headers=headers).json()["permissions"]["workspace.delete"] is True
    assert client.delete(base, headers=headers).status_code == 204


def test_owner_can_delete_workspace_without_membership(system):
    app, _, _, creator, _ = _setup(system)
    workspace = system["dao"].create_workspace(app["id"], "Private", creator_id=creator["id"])
    response = system["client"].delete(
        f"/api/v1/workspaces/{workspace['id']}", headers=system["headers"],
    )
    assert response.status_code == 204, response.text


def test_viewer_file_permissions_after_demotion(system):
    _, _, workspace, user, headers = _setup(system)
    repo, client = system["dao"], system["client"]
    membership = repo.add_workspace_member(workspace["id"], user_id=user["id"], role="editor")
    record = upload_file({**system, "headers": headers}, workspace_id=workspace["id"])
    repo.update_workspace_member(workspace["id"], membership["id"], role="viewer")
    base = f"/api/v1/workspaces/{workspace['id']}/files"
    assert client.get(base, headers=headers).status_code == 200
    assert client.post(f"{base}/upload-url", json={"filename": "new.txt"}, headers=headers).status_code == 403
    assert client.post(f"{base}/upload-url", json={"filename": "new.txt", "file_id": record["id"]}, headers=headers).status_code == 403
    assert client.delete(f"{base}/{record['id']}", headers=headers).status_code == 403


def test_workspace_user_directory_paginates_direct_org_and_enterprise_search(system):
    app, org, workspace, user, _ = _setup(system)
    repo, client = system["dao"], system["client"]
    headers = system["headers"]
    child = repo.create_org(app["id"], org["id"], "Child")
    for name in ["Staff Alpha", "Staff Beta", "Staff Percent%"]:
        repo.create_user(org_id=org["id"], name=name, password_hash=None)
    nested = repo.create_user(org_id=child["id"], name="Staff Child", password_hash=None)
    inactive = repo.create_user(org_id=org["id"], name="Staff Disabled", password_hash=None)
    repo.delete_user(inactive["id"])
    _, foreign_org = repo.create_app("Foreign", "foreign")
    repo.create_user(org_id=foreign_org["id"], name="Staff Foreign", password_hash=None)
    base = f"/api/v1/workspaces/{workspace['id']}"
    params = {"org_id": org["id"], "query": "staff", "page_size": 2}
    first = client.get(f"{base}/users", params=params, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 3
    assert first.json()["page"] == 1
    assert first.json()["page_size"] == 2
    assert len(first.json()["users"]) == 2
    second = client.get(f"{base}/users", params={**params, "page": 2}, headers=headers).json()
    assert len(second["users"]) == 1
    assert {u["id"] for u in first.json()["users"]}.isdisjoint({u["id"] for u in second["users"]})
    all_users = client.get(f"{base}/users", params={"query": "staff"}, headers=headers).json()
    assert all_users["total"] == 4
    assert nested["id"] in {u["id"] for u in all_users["users"]}
    assert user["id"] not in {u["id"] for u in all_users["users"]}
    assert client.get(f"{base}/users", params={"query": "%"}, headers=headers).json()["total"] == 1
    assert client.get(f"{base}/users", params={"org_id": foreign_org["id"]}, headers=headers).status_code == 422
    repo.delete_org(child["id"])
    assert client.get(f"{base}/users", params={"query": "staff"}, headers=headers).json()["total"] == 3
    assert child["id"] not in {o["id"] for o in client.get(f"{base}/orgs", headers=headers).json()["orgs"]}
    for params in [{"page": 0}, {"page_size": 101}]:
        assert client.get(f"{base}/users", params=params, headers=headers).status_code == 422
