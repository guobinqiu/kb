from kb_api.api.auth import hash_password


def test_workspace_membership_is_independent_of_organization(system):
    client = system["client"]
    dao = system["dao"]
    owner_headers = system["headers"]
    created = client.post(
        "/api/v1/apps",
        json={"app_id": "acme", "name": "Acme"},
        headers=owner_headers,
    )
    assert created.status_code == 201
    app = created.json()["app"]
    org = created.json()["org"]
    branch = dao.create_org(app["id"], org["id"], "Branch")
    member = dao.create_user(
        org_id=branch["id"], name="branch_member",
        password_hash=hash_password("password123"),
    )
    login = client.post("/api/v1/auth/login", json={"name": "branch_member", "password": "password123"})
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    created_workspace = client.post(
        f"/api/v1/apps/{app['app_id']}/workspaces",
        json={"name": "Shared Policies"}, headers=owner_headers,
    )
    assert created_workspace.status_code == 201
    workspace = created_workspace.json()["workspace"]
    assert workspace["app_id"] == app["id"]
    assert client.get(f"/api/v1/apps/{app['app_id']}/workspaces", headers=member_headers).json() == {
        "workspaces": [], "permissions": {"workspace.create": True},
    }

    added = client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"type": "user", "id": member["id"], "role": "editor"}, headers=owner_headers,
    )
    assert added.status_code == 201
    visible = client.get(f"/api/v1/apps/{app['app_id']}/workspaces", headers=member_headers)
    assert [item["id"] for item in visible.json()["workspaces"]] == [workspace["id"]]

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}", headers=member_headers)
    assert detail.status_code == 200
    assert detail.json()["permissions"] == {
        "workspace.update": False,
        "workspace.delete": False,
        "workspace.members.manage": False,
        "workspace.files.read": True,
        "workspace.files.upload": True,
        "workspace.files.delete": True,
        "workspace.search": True,
    }
    assert client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"type": "user", "id": member["id"], "role": "editor"}, headers=member_headers,
    ).status_code == 403
    assert client.delete(
        f"/api/v1/workspaces/{workspace['id']}/members/{added.json()['member']['id']}?type=user",
        headers=member_headers,
    ).status_code == 403


def test_member_can_create_workspace_in_own_app_and_manage_its_members(system):
    client = system["client"]
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    other_app, _ = dao.create_app("Other", "other")
    member = dao.create_user(
        org_id=org["id"], name="creator_member",
        password_hash=hash_password("password123"),
    )
    colleague = dao.create_user(
        org_id=org["id"], name="colleague",
        password_hash=hash_password("password123"),
    )
    login = client.post("/api/v1/auth/login", json={"name": member["name"], "password": "password123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(f"/api/v1/apps/{app['app_id']}/workspaces", json={"name": "Member Workspace"}, headers=headers)
    assert response.status_code == 201
    workspace = response.json()["workspace"]
    assert workspace["created_by"] == member["id"]
    detail = client.get(f"/api/v1/workspaces/{workspace['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["role"] == "admin"
    assert detail.json()["permissions"]["workspace.members.manage"] is True
    assert client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"type": "user", "id": colleague["id"], "role": "editor"}, headers=headers,
    ).status_code == 201
    assert client.post(
        f"/api/v1/apps/{other_app['app_id']}/workspaces", json={"name": "Forbidden"}, headers=headers,
    ).status_code == 403
    assert dao.list_workspaces(other_app["id"]) == []


def test_search_uses_authorized_workspaces_not_organization_subtree(system):
    client = system["client"]
    dao = system["dao"]
    owner_headers = system["headers"]
    app, org = dao.create_app("Acme", "acme")
    branch = dao.create_org(app["id"], org["id"], "Branch")
    user = dao.create_user(
        org_id=branch["id"], name="branch_member",
        password_hash=hash_password("password123"),
    )
    login = client.post("/api/v1/auth/login", json={"name": user["name"], "password": "password123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}", "X-App-Id": app["app_id"]}
    first = client.post(f"/api/v1/apps/{app['app_id']}/workspaces", json={"name": "Policies"}, headers=owner_headers).json()["workspace"]
    second = client.post(f"/api/v1/apps/{app['app_id']}/workspaces", json={"name": "Finance"}, headers=owner_headers).json()["workspace"]
    client.post(f"/api/v1/workspaces/{first['id']}/members", json={"type": "user", "id": user["id"], "role": "viewer"}, headers=owner_headers)

    response = client.post("/api/v1/rag/search", json={"query": "policy"}, headers=headers)
    assert response.status_code == 200
    assert system["search_service"].requests[-1]["json"]["workspace_ids"] == [first["id"]]
    assert "org_ids" not in system["search_service"].requests[-1]["json"]
    forbidden = client.post("/api/v1/rag/search", json={"query": "policy", "workspace_ids": [second["id"]]}, headers=headers)
    assert forbidden.status_code == 403


def test_app_cannot_be_deleted_while_it_contains_workspaces(system):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    dao.create_workspace(app["id"], "Policies")

    response = system["client"].delete(f"/api/v1/apps/{app['app_id']}", headers=system["headers"])

    assert response.status_code == 409
    assert dao.get_app(app["id"]) is not None
