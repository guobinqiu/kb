from kb_api.auth import hash_password


def _login(system, name, password):
    response = system["client"].post("/api/v1/auth/login", json={"name": name, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _org(system, app_id="acme"):
    response = system["client"].post("/api/v1/apps", json={"app_id": app_id, "name": app_id}, headers=system["headers"])
    assert response.status_code == 201
    return response.json()["org"]


def test_member_cannot_manage_accounts_but_can_change_own_password(system):
    org = _org(system)
    member = system["repository"].create_user(org_id=org["id"], name="member", password_hash=hash_password("old-password"))
    headers = _login(system, "member", "old-password")
    client = system["client"]
    assert client.post("/api/v1/users", json={"org_id": org["id"], "name": "other", "password": "password-123"}, headers=headers).status_code == 403
    assert client.put(f"/api/v1/users/{member['id']}", json={"role": "admin"}, headers=headers).status_code == 409
    assert client.delete(f"/api/v1/users/{member['id']}", headers=headers).status_code == 409
    assert client.patch("/api/v1/auth/password", json={"old_password": "wrong", "new_password": "new-password"}, headers=headers).status_code == 403
    assert client.patch("/api/v1/auth/password", json={"old_password": "old-password", "new_password": "new-password"}, headers=headers).status_code == 200
    assert client.post("/api/v1/auth/login", json={"name": "member", "password": "old-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"name": "member", "password": "new-password"}).status_code == 200


def test_admin_can_grant_admin_in_subtree_but_not_owner(system):
    org = _org(system)
    other = _org(system, "other")
    client = system["client"]
    response = client.post("/api/v1/users", json={"org_id": org["id"], "name": "manager", "password": "password-123", "role": "admin"}, headers=system["headers"])
    assert response.status_code == 201
    headers = _login(system, "manager", "password-123")
    assert client.post("/api/v1/users", json={"org_id": org["id"], "name": "peer", "password": "password-123", "role": "admin"}, headers=headers).status_code == 201
    assert client.post("/api/v1/users", json={"org_id": None, "name": "owner2", "password": "password-123", "role": "owner"}, headers=headers).status_code == 403
    assert client.post("/api/v1/users", json={"org_id": other["id"], "name": "outsider", "password": "password-123"}, headers=headers).status_code == 403
    employee = client.post("/api/v1/users", json={"org_id": org["id"], "name": "employee", "password": "password-123"}, headers=system["headers"]).json()
    assert client.put(f"/api/v1/users/{employee['id']}", json={"role": "admin"}, headers=headers).status_code == 200
    assert client.put(f"/api/v1/users/{system['admin']['id']}", json={"role": "member"}, headers=headers).status_code in (403, 404)
    assert client.get("/api/v1/auth/me", headers=system["headers"]).json()["is_platform_admin"] is True
    assert client.get("/api/v1/auth/me", headers=headers).json()["is_platform_admin"] is False


def test_disabled_user_old_token_revoked_and_restored(system):
    org = _org(system)
    client = system["client"]
    member = client.post("/api/v1/users", json={"org_id": org["id"], "name": "member", "password": "password-123"}, headers=system["headers"]).json()
    headers = _login(system, "member", "password-123")
    assert client.delete(f"/api/v1/users/{member['id']}", headers=system["headers"]).status_code == 204
    assert member["id"] not in {item["id"] for item in client.get("/api/v1/users", headers=system["headers"]).json()["users"]}
    assert member["id"] in {item["id"] for item in client.get("/api/v1/users", params={"include_disabled": True}, headers=system["headers"]).json()["users"]}
    assert client.post("/api/v1/auth/login", json={"name": "member", "password": "password-123"}).json()["error"] == "Account disabled"
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.put(f"/api/v1/users/{member['id']}", json={"deleted_at": None}, headers=system["headers"]).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_member_cannot_read_disabled_user_directly(system):
    org = _org(system)
    client = system["client"]
    client.post("/api/v1/users", json={"org_id": org["id"], "name": "viewer", "password": "password-123"}, headers=system["headers"])
    target = client.post("/api/v1/users", json={"org_id": org["id"], "name": "target", "password": "password-123"}, headers=system["headers"]).json()
    headers = _login(system, "viewer", "password-123")
    assert client.delete(f"/api/v1/users/{target['id']}", headers=system["headers"]).status_code == 204
    assert client.get(f"/api/v1/users/{target['id']}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/users/{target['id']}", headers=system["headers"]).status_code == 200


def test_existing_token_uses_current_role(system):
    org = _org(system)
    client = system["client"]
    user = client.post("/api/v1/users", json={"org_id": org["id"], "name": "employee", "password": "password-123"}, headers=system["headers"]).json()
    headers = _login(system, "employee", "password-123")
    assert client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Branch"}, headers=headers).status_code == 403
    assert client.put(f"/api/v1/users/{user['id']}", json={"role": "admin"}, headers=system["headers"]).status_code == 200
    assert client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Branch"}, headers=headers).status_code == 201
    assert client.put(f"/api/v1/users/{user['id']}", json={"role": "member"}, headers=system["headers"]).status_code == 200
    assert client.post("/api/v1/orgs", json={"parent_id": org["id"], "name": "Second"}, headers=headers).status_code == 403


def test_owner_accounts_are_orgless(system):
    org = _org(system)
    client = system["client"]
    response = client.post("/api/v1/users", json={"org_id": org["id"], "name": "misplaced-owner", "password": "password-123", "role": "owner"}, headers=system["headers"])
    assert response.status_code == 422
    response = client.post("/api/v1/users", json={"org_id": None, "name": "owner2", "password": "password-123", "role": "owner"}, headers=system["headers"])
    assert response.status_code == 201
    owner2 = response.json()
    owner_headers = _login(system, "owner2", "password-123")
    assert client.post("/api/v1/apps", json={"app_id": "other", "name": "Other"}, headers=owner_headers).status_code == 201
    assert client.put(f"/api/v1/users/{system['admin']['id']}", json={"password": "managed-password"}, headers=owner_headers).status_code == 200
    assert client.put(f"/api/v1/users/{owner2['id']}", json={"password": "self-password"}, headers=owner_headers).status_code == 409
    assert client.put(f"/api/v1/users/{owner2['id']}", json={"org_id": org["id"]}, headers=system["headers"]).status_code == 409
    assert client.put(f"/api/v1/users/{owner2['id']}", json={"role": "member"}, headers=system["headers"]).status_code == 409
    assert client.put(f"/api/v1/users/{owner2['id']}", json={"role": "member", "org_id": org["id"]}, headers=system["headers"]).status_code == 200
