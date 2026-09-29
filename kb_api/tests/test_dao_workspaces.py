
import pytest


def _app_tree(dao, name: str, business_id: str):
    app, org = dao.create_app(name, business_id)
    branch = dao.create_org(app["id"], org["id"], f"{name} Branch")
    return app, org, branch


def test_workspace_crud_is_scoped_to_app(system):
    dao = system["dao"]
    first, _, _ = _app_tree(dao, "First", "first")
    second, _, _ = _app_tree(dao, "Second", "second")
    workspace = dao.create_workspace(first["id"], "Policies")
    assert dao.get_workspace(workspace["id"]) == workspace
    assert dao.list_workspaces(first["id"]) == [workspace]
    assert dao.list_workspaces(second["id"]) == []
    assert dao.update_workspace(workspace["id"], "Shared Policies")["name"] == "Shared Policies"
    assert dao.delete_workspace(workspace["id"]) is True
    assert dao.get_workspace(workspace["id"]) is None


def test_personal_workspace_membership_does_not_grant_access_to_org_peers(system):
    dao = system["dao"]
    app, org, branch = _app_tree(dao, "Acme", "acme")
    branch_user = dao.create_user(org_id=branch["id"], name="branch-user", password_hash=None)
    org_user = dao.create_user(org_id=org["id"], name="org-user", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies")
    assert [user["id"] for user in dao.list_org_users(branch["id"])] == [branch_user["id"]]
    member = dao.add_workspace_member(workspace["id"], user_id=branch_user["id"])
    assert dao.add_workspace_member(workspace["id"], user_id=branch_user["id"])["id"] == member["id"]
    assert dao.has_workspace_access(branch_user, workspace["id"]) is True
    assert dao.has_workspace_access(org_user, workspace["id"]) is False
    newcomer = dao.create_user(org_id=branch["id"], name="newcomer", password_hash=None)
    assert dao.has_workspace_access(newcomer, workspace["id"]) is False
    assert dao.list_workspace_members(workspace["id"])[0]["name"] == "branch-user"
    assert dao.delete_workspace_member(workspace["id"], member["id"]) is True
    assert dao.has_workspace_access(branch_user, workspace["id"]) is False


def test_owner_and_enterprise_admin_require_explicit_workspace_membership(system):
    dao = system["dao"]
    first, first_org, _ = _app_tree(dao, "First", "first")
    second, second_org, _ = _app_tree(dao, "Second", "second")
    first_workspace = dao.create_workspace(first["id"], "First Workspace")
    second_workspace = dao.create_workspace(second["id"], "Second Workspace")
    owner = system["admin"]
    admin = dao.create_user(org_id=first_org["id"], name="first-admin", password_hash=None, role="admin")
    other_admin = dao.create_user(org_id=second_org["id"], name="second-admin", password_hash=None, role="admin")
    assert dao.has_workspace_access(owner, first_workspace["id"]) is False
    assert dao.has_workspace_access(owner, second_workspace["id"]) is False
    assert dao.has_workspace_access(admin, first_workspace["id"]) is False
    assert dao.has_workspace_access(admin, second_workspace["id"]) is False
    assert dao.has_workspace_access(other_admin, first_workspace["id"]) is False
    dao.add_workspace_member(first_workspace["id"], user_id=owner["id"], role="viewer")
    dao.add_workspace_member(first_workspace["id"], user_id=admin["id"], role="editor")
    dao.add_workspace_member(first_workspace["id"], user_id=other_admin["id"], role="admin")
    assert dao.get_workspace_role(owner, first_workspace["id"]) == "viewer"
    assert dao.get_workspace_role(admin, first_workspace["id"]) == "editor"
    assert dao.get_workspace_role(other_admin, first_workspace["id"]) is None
    assert dao.has_workspace_access(owner, second_workspace["id"]) is False


def test_org_workspace_grant_is_dynamic_and_only_applies_to_direct_users(system):
    dao = system["dao"]
    app, org, branch = _app_tree(dao, "Acme", "acme")
    leaf = dao.create_org(app["id"], branch["id"], "Leaf")
    direct = dao.create_user(org_id=branch["id"], name="direct", password_hash=None)
    parent = dao.create_user(org_id=org["id"], name="parent", password_hash=None)
    child = dao.create_user(org_id=leaf["id"], name="child", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies")
    grant = dao.add_workspace_org(workspace["id"], org_id=branch["id"])
    assert grant["role"] == "viewer"
    newcomer = dao.create_user(org_id=branch["id"], name="newcomer", password_hash=None)
    for user in (direct, newcomer):
        assert dao.get_workspace_role(user, workspace["id"]) == "viewer"
    for user in (parent, child):
        assert dao.get_workspace_role(user, workspace["id"]) is None
    members = dao.list_workspace_members(workspace["id"])
    assert len(members) == 1
    assert {key: members[0][key] for key in ("id", "type", "org_id", "name", "role")} == {
        "id": grant["id"], "type": "org", "org_id": branch["id"], "name": branch["name"], "role": "viewer",
    }
    updated = dao.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    assert updated["id"] == grant["id"]
    assert dao.get_workspace_role(newcomer, workspace["id"]) == "editor"
    assert dao.update_workspace_org(workspace["id"], grant["id"], role="viewer")["role"] == "viewer"
    assert dao.get_workspace_role(direct, workspace["id"]) == "viewer"
    assert dao.delete_workspace_org(workspace["id"], grant["id"]) is True
    assert dao.get_workspace_role(newcomer, workspace["id"]) is None


def test_personal_viewer_overrides_org_editor_and_deletion_restores_org_role(system):
    dao = system["dao"]
    app, _, branch = _app_tree(dao, "Acme", "acme")
    user = dao.create_user(org_id=branch["id"], name="reader", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies")
    dao.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    member = dao.add_workspace_member(workspace["id"], user_id=user["id"], role="viewer")
    assert dao.get_workspace_role(user, workspace["id"]) == "viewer"
    rows = {row["type"]: row for row in dao.list_workspace_members(workspace["id"])}
    assert set(rows) == {"user", "org"}
    assert {key: rows["user"][key] for key in ("id", "user_id", "name", "role")} == {
        "id": member["id"], "user_id": user["id"], "name": user["name"], "role": "viewer",
    }
    assert dao.delete_workspace_member(workspace["id"], member["id"]) is True
    assert dao.get_workspace_role(user, workspace["id"]) == "editor"


@pytest.mark.parametrize("personal", [False, True], ids=["org-grant", "personal-grant"])
def test_workspace_role_tracks_transfers_and_rejects_cross_app_users(system, personal):
    dao = system["dao"]
    app, org, branch = _app_tree(dao, "Acme", "acme")
    _, other_org, _ = _app_tree(dao, "Other", "other")
    user = dao.create_user(org_id=branch["id"], name="moving", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies")
    dao.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    if personal:
        dao.add_workspace_member(workspace["id"], user_id=user["id"], role="viewer")
    expected = "viewer" if personal else "editor"
    assert dao.get_workspace_role(user, workspace["id"]) == expected
    dao.update_user(user["id"], org_id=org["id"])
    assert dao.get_workspace_role(user, workspace["id"]) == ("viewer" if personal else None)
    dao.update_user(user["id"], org_id=branch["id"])
    assert dao.get_workspace_role(user, workspace["id"]) == expected
    dao.update_user(user["id"], org_id=other_org["id"])
    dao.add_workspace_org(workspace["id"], org_id=other_org["id"], role="editor")
    assert dao.get_workspace_role(user, workspace["id"]) is None
    assert dao.has_workspace_access(user, workspace["id"]) is False


@pytest.mark.parametrize("personal", [False, True], ids=["org-grant", "personal-grant"])
@pytest.mark.parametrize("disabled", ["user", "department", "ancestor"])
def test_workspace_role_rechecks_disabled_users_and_org_ancestors(system, personal, disabled):
    dao = system["dao"]
    app, _, branch = _app_tree(dao, "Acme", "acme")
    leaf = dao.create_org(app["id"], branch["id"], "Leaf")
    user = dao.create_user(org_id=leaf["id"], name="member", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies")
    if personal:
        dao.add_workspace_member(workspace["id"], user_id=user["id"])
    else:
        dao.add_workspace_org(workspace["id"], org_id=leaf["id"], role="editor")
    assert dao.get_workspace_role(user, workspace["id"]) == "editor"
    if disabled == "user":
        dao.delete_user(user["id"])
    else:
        assert dao.delete_org(leaf["id"] if disabled == "department" else branch["id"]) is True
    # Keep the original user dict to verify that authorization reads current database state.
    assert dao.get_workspace_role(user, workspace["id"]) is None
    assert dao.has_workspace_access(user, workspace["id"]) is False


def _revoke_admin(dao, workspace_id, member, operation):
    if operation == "delete":
        return dao.delete_workspace_member(workspace_id, member["id"])
    if operation == "update":
        return dao.update_workspace_member(workspace_id, member["id"], role="viewer")
    return dao.add_workspace_member(workspace_id, user_id=member["user_id"], role="editor")


@pytest.mark.parametrize("creator_kind", ["owner", "org-user"])
@pytest.mark.parametrize("operation", ["delete", "update", "upsert"])
def test_creator_gets_personal_admin_and_last_admin_cannot_be_revoked(system, creator_kind, operation):
    dao = system["dao"]
    app, _, branch = _app_tree(dao, "Acme", "acme")
    creator = system["admin"] if creator_kind == "owner" else dao.create_user(
        org_id=branch["id"], name="creator", password_hash=None,
    )
    workspace = dao.create_workspace(app["id"], "Policies", creator_id=creator["id"])
    members = dao.list_workspace_members(workspace["id"])
    assert len(members) == 1
    assert members[0]["type"] == "user"
    assert members[0]["user_id"] == creator["id"]
    assert dao.get_workspace_role(creator, workspace["id"]) == "admin"
    with pytest.raises(ValueError, match="^Workspace must retain an administrator$"):
        _revoke_admin(dao, workspace["id"], members[0], operation)
    assert dao.list_workspace_members(workspace["id"]) == members
    assert dao.get_workspace_role(creator, workspace["id"]) == "admin"


@pytest.mark.parametrize("invalid_admin", ["disabled-user", "disabled-org", "disabled-ancestor", "cross-app"])
@pytest.mark.parametrize("operation", ["delete", "update", "upsert"])
def test_only_effective_personal_admins_count_for_last_admin_guard(system, invalid_admin, operation):
    dao = system["dao"]
    app, _, branch = _app_tree(dao, "Acme", "acme")
    leaf = dao.create_org(app["id"], branch["id"], "Leaf")
    user = dao.create_user(org_id=leaf["id"], name="other-admin", password_hash=None)
    workspace = dao.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    owner_member = dao.list_workspace_members(workspace["id"])[0]
    other_member = dao.add_workspace_member(workspace["id"], user_id=user["id"], role="admin")
    dao.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    if invalid_admin == "disabled-user":
        dao.delete_user(user["id"])
    elif invalid_admin == "disabled-org":
        assert dao.delete_org(leaf["id"]) is True
    elif invalid_admin == "disabled-ancestor":
        assert dao.delete_org(branch["id"]) is True
    else:
        _, other_org, _ = _app_tree(dao, "Other", "other")
        dao.update_user(user["id"], org_id=other_org["id"])
    assert dao.get_workspace_role(user, workspace["id"]) is None
    with pytest.raises(ValueError, match="^Workspace must retain an administrator$"):
        _revoke_admin(dao, workspace["id"], owner_member, operation)
    assert dao.get_workspace_role(system["admin"], workspace["id"]) == "admin"
    assert dao.delete_workspace_member(workspace["id"], other_member["id"]) is True


@pytest.mark.parametrize("role", ["admin", "owner", "member", "", None])
def test_org_grants_reject_invalid_roles_on_add_and_update(system, role):
    dao = system["dao"]
    app, _, branch = _app_tree(dao, "Acme", "acme")
    workspace = dao.create_workspace(app["id"], "Policies")
    grant = dao.add_workspace_org(workspace["id"], org_id=branch["id"])
    with pytest.raises(ValueError, match="^Invalid workspace role$"):
        dao.add_workspace_org(workspace["id"], org_id=branch["id"], role=role)
    with pytest.raises(ValueError, match="^Invalid workspace role$"):
        dao.update_workspace_org(workspace["id"], grant["id"], role=role)
    assert dao.list_workspace_members(workspace["id"])[0]["role"] == "viewer"


def test_list_orgs_returns_complete_app_tree_without_crossing_apps(system):
    dao = system["dao"]
    first, first_root, first_branch = _app_tree(dao, "First", "first")
    sibling = dao.create_org(first["id"], first_root["id"], "Sibling")
    leaf = dao.create_org(first["id"], first_branch["id"], "Leaf")
    _, second_root, _ = _app_tree(dao, "Second", "second")
    visible = dao.list_orgs(first_branch["id"])
    assert [org["id"] for org in visible] == [first_root["id"], first_branch["id"], sibling["id"], leaf["id"]]
    assert second_root["id"] not in {org["id"] for org in visible}
    dao.delete_org(first_branch["id"])
    assert [org["id"] for org in dao.list_orgs(leaf["id"])] == [first_root["id"], sibling["id"]]
    assert [org["id"] for org in dao.list_orgs(leaf["id"], include_disabled=True)] == [first_root["id"], first_branch["id"], sibling["id"], leaf["id"]]
    assert leaf["id"] not in {org["id"] for org in dao.list_orgs(None)}


def test_owner_lists_all_orgs_without_platform_root(system):
    dao = system["dao"]
    _, first_root, _ = _app_tree(dao, "First", "first")
    _, second_root, _ = _app_tree(dao, "Second", "second")
    assert {first_root["id"], second_root["id"]} <= {org["id"] for org in dao.list_orgs(None)}


def test_workspace_files_do_not_require_org_and_can_move_workspaces(system):
    dao = system["dao"]
    app, _, _ = _app_tree(dao, "Acme", "acme")
    source = dao.create_workspace(app["id"], "Source")
    target = dao.create_workspace(app["id"], "Target")
    record = dao.create_file(workspace_id=source["id"], filename="policy.txt", status="uploaded")
    assert "org_id" not in record
    assert dao.list_workspace_files(source["id"]) == [record]
    moved = dao.update_file(record["id"], workspace_id=target["id"], filename="renamed.txt")
    assert moved["workspace_id"] == target["id"]
    assert moved["filename"] == "renamed.txt"
    assert dao.list_workspace_files(source["id"]) == []
    assert dao.list_workspace_files(target["id"]) == [moved]
