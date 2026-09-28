from kb_api.auth import hash_password


def _create_app(system, name="Acme"):
    response = system["client"].post("/api/v1/apps", json={"name": name, "app_id": name.lower()}, headers=system["headers"])
    assert response.status_code == 201
    return response.json()


def test_app_create_returns_app_and_top_level_org(system):
    payload = _create_app(system)
    assert set(payload) == {"app", "org"}
    assert payload["app"]["name"] == "Acme"
    assert payload["app"]["app_id"] == "acme"
    assert payload["org"]["app_id"] == payload["app"]["id"]
    assert payload["org"]["parent_id"] is None
    assert system["client"].get("/api/v1/apps", headers=system["headers"]).json()["apps"] == [payload["app"]]


def test_business_app_id_must_be_unique_and_valid(system):
    _create_app(system)
    duplicate = system["client"].post(
        "/api/v1/apps", json={"name": "Another", "app_id": "acme"}, headers=system["headers"]
    )
    invalid = system["client"].post(
        "/api/v1/apps", json={"name": "Invalid", "app_id": "123"}, headers=system["headers"]
    )
    assert duplicate.status_code == 409
    assert invalid.status_code == 422


def test_orgs_and_users_crud_are_subtree_scoped(system):
    created = _create_app(system)
    org = created["org"]
    child_response = system["client"].post(
        "/api/v1/orgs",
        json={"parent_id": org["id"], "name": "Branch"},
        headers=system["headers"],
    )
    assert child_response.status_code == 201
    child = child_response.json()
    user_response = system["client"].post(
        "/api/v1/users",
        json={"org_id": org["id"], "name": "manager", "password": "manager-password", "role": "admin"},
        headers=system["headers"],
    )
    assert user_response.status_code == 201
    manager = user_response.json()
    assert "password_hash" not in manager

    login = system["client"].post(
        "/api/v1/auth/login", json={"name": "manager", "password": "manager-password"}
    )
    manager_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    orgs = system["client"].get("/api/v1/orgs", headers=manager_headers).json()["orgs"]
    assert {org["id"] for org in orgs} == {org["id"], child["id"]}
    users = system["client"].get("/api/v1/users", headers=manager_headers).json()["users"]
    assert [user["id"] for user in users] == [manager["id"]]

    other = _create_app(system, "Other")["org"]
    forbidden = system["client"].post(
        "/api/v1/users",
        json={"org_id": other["id"], "name": "intruder", "password": "password-123"},
        headers=manager_headers,
    )
    assert forbidden.status_code == 403


def test_org_list_is_subtree_scoped_without_granting_workspace_access(system):
    created = _create_app(system)
    org = created["org"]
    branch = system["repository"].create_org(created["app"]["id"], org["id"], "Branch")
    leaf = system["repository"].create_org(created["app"]["id"], branch["id"], "Leaf")
    system["repository"].create_org(created["app"]["id"], org["id"], "Sibling")
    user = system["repository"].create_user(
        org_id=branch["id"], name="branch-member", password_hash=hash_password("password-123")
    )
    login = system["client"].post("/api/v1/auth/login", json={"name": user["name"], "password": "password-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = system["client"].get(f"/api/v1/orgs?app_id={created['app']['id']}", headers=headers)
    assert response.status_code == 200
    assert {org["id"] for org in response.json()["orgs"]} == {branch["id"], leaf["id"]}
    workspace = system["client"].post(
        f"/api/v1/apps/{created['app']['id']}/workspaces", json={"name": "Private"}, headers=system["headers"]
    ).json()["workspace"]
    assert system["client"].get(f"/api/v1/workspaces/{workspace['id']}/files", headers=headers).status_code == 404
    assert system["client"].get(f"/api/v1/orgs/{org['id']}", headers=headers).status_code == 404


def test_management_put_and_delete(system):
    created = _create_app(system)
    app_id = created["app"]["id"]
    org_id = created["org"]["id"]
    updated_app = system["client"].put(
        f"/api/v1/apps/{app_id}", json={"name": "Renamed"}, headers=system["headers"]
    )
    assert updated_app.status_code == 200
    assert updated_app.json()["name"] == "Renamed"

    user = system["repository"].create_user(
        org_id=org_id, name="member", password_hash=hash_password("password-123")
    )
    updated_user = system["client"].put(
        f"/api/v1/users/{user['id']}", json={"role": "admin"}, headers=system["headers"]
    )
    assert updated_user.json()["role"] == "admin"
    assert system["client"].delete(f"/api/v1/users/{user['id']}", headers=system["headers"]).status_code == 204
    assert system["client"].delete(f"/api/v1/apps/{app_id}", headers=system["headers"]).status_code == 204


def test_user_response_uses_name_without_display_name(system):
    org = _create_app(system)["org"]
    response = system["client"].post(
        "/api/v1/users",
        json={"org_id": org["id"], "name": "reader", "password": "password-123"},
        headers=system["headers"],
    )
    assert response.status_code == 201
    assert response.json()["name"] == "reader"
    assert "username" not in response.json()
    assert "display_name" not in response.json()


def test_management_lists_are_scoped_by_requested_app_and_org(system):
    first = _create_app(system, "First")
    second = _create_app(system, "Second")
    branch = system["client"].post(
        "/api/v1/orgs",
        json={"parent_id": first["org"]["id"], "name": "Branch"},
        headers=system["headers"],
    ).json()
    first_user = system["client"].post(
        "/api/v1/users",
        json={"org_id": first["org"]["id"], "name": "first", "password": "password-123"},
        headers=system["headers"],
    ).json()
    branch_user = system["client"].post(
        "/api/v1/users",
        json={"org_id": branch["id"], "name": "branch", "password": "password-123"},
        headers=system["headers"],
    ).json()

    orgs = system["client"].get(
        "/api/v1/orgs", params={"app_id": first["app"]["id"]}, headers=system["headers"]
    ).json()["orgs"]
    users = system["client"].get(
        "/api/v1/users", params={"org_id": branch["id"]}, headers=system["headers"]
    ).json()["users"]

    assert {org["id"] for org in orgs} == {first["org"]["id"], branch["id"]}
    assert second["org"]["id"] not in {org["id"] for org in orgs}
    assert [user["id"] for user in users] == [branch_user["id"]]
    assert first_user["id"] not in {user["id"] for user in users}


def test_org_user_does_not_receive_app_api_key_or_admin_capability(system):
    created = _create_app(system)
    system["client"].post(
        "/api/v1/users",
        json={
            "org_id": created["org"]["id"],
            "name": "org-admin",
            "password": "password-123",
        },
        headers=system["headers"],
    )
    login = system["client"].post(
        "/api/v1/auth/login", json={"name": "org-admin", "password": "password-123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    app = system["client"].get("/api/v1/apps", headers=headers).json()["apps"][0]
    me = system["client"].get("/api/v1/auth/me", headers=headers).json()

    assert "api_key" not in app
    assert me["is_platform_admin"] is False
    assert system["client"].get("/api/v1/auth/me", headers=system["headers"]).json()["is_platform_admin"] is True
