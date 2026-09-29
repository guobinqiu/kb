import pytest


def test_workspace_delete_cleans_grants_and_deleted_files(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    dao.add_workspace_org(workspace["id"], org_id=org["id"])
    record = dao.create_file(workspace_id=workspace["id"], filename="policy.txt")
    dao.update_file(record["id"], deleted_at="2026-09-29T00:00:00+00:00")

    response = system["client"].delete(f"/api/v1/workspaces/{workspace['id']}", headers=system["headers"])

    assert response.status_code == 204
    assert dao.get_workspace(workspace["id"]) is None
    assert dao.list_workspace_members(workspace["id"]) == []
    assert dao.get_file(record["id"], include_deleted=True) is None


def test_workspace_delete_with_live_files_retains_grants(system):
    dao = system["dao"]
    app, _ = dao.create_app("Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    record = dao.create_file(workspace_id=workspace["id"], filename="policy.txt")
    with pytest.raises(ValueError, match="Workspace contains files"):
        dao.delete_workspace(workspace["id"])
    assert dao.get_workspace(workspace["id"]) == workspace
    assert len(dao.list_workspace_members(workspace["id"])) == 1
    assert dao.get_file(record["id"]) == record


def test_app_delete_with_orgs_preserves_users_and_references(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    branch = dao.create_org(app["id"], org["id"], "Branch")
    user = dao.create_user(org_id=branch["id"], name="employee", password_hash=None)
    other, _ = dao.create_app("Other", "other")
    workspace = dao.create_workspace(other["id"], "Other policies")
    dao.add_workspace_member(workspace["id"], user_id=user["id"])
    dao.add_workspace_org(workspace["id"], org_id=branch["id"])
    record = dao.create_file(workspace_id=workspace["id"], filename="policy.txt", created_by=user["id"])

    with pytest.raises(ValueError, match="App contains orgs"):
        dao.delete_app(app["id"])
    assert dao.get_app(app["id"]) == app
    assert dao.get_org(org["id"]) == org
    assert dao.get_org(branch["id"]) == branch
    assert dao.get_user(user["id"]) == user
    assert len(dao.list_workspace_members(workspace["id"])) == 2
    assert dao.get_file(record["id"])["created_by"] == user["id"]
    assert dao.get_app(other["id"]) == other


def test_app_delete_rejects_top_level_org(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    response = system["client"].delete(f"/api/v1/apps/{app['id']}", headers=system["headers"])
    assert response.status_code == 409
    assert response.json()["error"] == "App contains orgs"
    assert dao.get_org(org["id"]) == org


def test_app_delete_with_workspace_preserves_orgs(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    dao.create_workspace(app["id"], "Policies")
    with pytest.raises(ValueError, match="App contains workspaces"):
        dao.delete_app(app["id"])
    assert dao.get_app(app["id"]) == app
    assert dao.get_org(org["id"]) == org


def test_empty_disabled_org_delete_cleans_workspace_grants(system):
    dao = system["dao"]
    app, org = dao.create_app("Acme", "acme")
    branch = dao.create_org(app["id"], org["id"], "Branch")
    workspace = dao.create_workspace(app["id"], "Policies")
    dao.add_workspace_org(workspace["id"], org_id=branch["id"])
    dao.delete_org(branch["id"])

    assert dao.purge_org(branch["id"]) is True
    assert dao.get_org(branch["id"]) is None
    assert dao.list_workspace_members(workspace["id"]) == []
