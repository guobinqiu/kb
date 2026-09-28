from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest


def _app_tree(repository, name: str, business_id: str):
    app, org = repository.create_app(name, business_id)
    branch = repository.create_org(app["id"], org["id"], f"{name} Branch")
    return app, org, branch


def test_workspace_crud_is_scoped_to_app(system):
    repository = system["repository"]
    first, _, _ = _app_tree(repository, "First", "first")
    second, _, _ = _app_tree(repository, "Second", "second")
    workspace = repository.create_workspace(first["id"], "Policies")
    assert repository.get_workspace(workspace["id"]) == workspace
    assert repository.list_workspaces(first["id"]) == [workspace]
    assert repository.list_workspaces(second["id"]) == []
    assert repository.update_workspace(workspace["id"], "Shared Policies")["name"] == "Shared Policies"
    assert repository.delete_workspace(workspace["id"]) is True
    assert repository.get_workspace(workspace["id"]) is None


def test_personal_workspace_membership_does_not_grant_access_to_org_peers(system):
    repository = system["repository"]
    app, org, branch = _app_tree(repository, "Acme", "acme")
    branch_user = repository.create_user(org_id=branch["id"], name="branch-user", password_hash=None)
    org_user = repository.create_user(org_id=org["id"], name="org-user", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies")
    assert [user["id"] for user in repository.list_org_users(branch["id"])] == [branch_user["id"]]
    member = repository.add_workspace_member(workspace["id"], user_id=branch_user["id"])
    assert repository.add_workspace_member(workspace["id"], user_id=branch_user["id"])["id"] == member["id"]
    assert repository.has_workspace_access(branch_user, workspace["id"]) is True
    assert repository.has_workspace_access(org_user, workspace["id"]) is False
    newcomer = repository.create_user(org_id=branch["id"], name="newcomer", password_hash=None)
    assert repository.has_workspace_access(newcomer, workspace["id"]) is False
    assert repository.list_workspace_members(workspace["id"])[0]["name"] == "branch-user"
    assert repository.delete_workspace_member(workspace["id"], member["id"]) is True
    assert repository.has_workspace_access(branch_user, workspace["id"]) is False


def test_owner_and_enterprise_admin_require_explicit_workspace_membership(system):
    repository = system["repository"]
    first, first_org, _ = _app_tree(repository, "First", "first")
    second, second_org, _ = _app_tree(repository, "Second", "second")
    first_workspace = repository.create_workspace(first["id"], "First Workspace")
    second_workspace = repository.create_workspace(second["id"], "Second Workspace")
    owner = system["admin"]
    admin = repository.create_user(org_id=first_org["id"], name="first-admin", password_hash=None, role="admin")
    other_admin = repository.create_user(org_id=second_org["id"], name="second-admin", password_hash=None, role="admin")
    assert repository.has_workspace_access(owner, first_workspace["id"]) is False
    assert repository.has_workspace_access(owner, second_workspace["id"]) is False
    assert repository.has_workspace_access(admin, first_workspace["id"]) is False
    assert repository.has_workspace_access(admin, second_workspace["id"]) is False
    assert repository.has_workspace_access(other_admin, first_workspace["id"]) is False
    repository.add_workspace_member(first_workspace["id"], user_id=owner["id"], role="viewer")
    repository.add_workspace_member(first_workspace["id"], user_id=admin["id"], role="editor")
    repository.add_workspace_member(first_workspace["id"], user_id=other_admin["id"], role="admin")
    assert repository.get_workspace_role(owner, first_workspace["id"]) == "viewer"
    assert repository.get_workspace_role(admin, first_workspace["id"]) == "editor"
    assert repository.get_workspace_role(other_admin, first_workspace["id"]) is None
    assert repository.has_workspace_access(owner, second_workspace["id"]) is False


def test_org_workspace_grant_is_dynamic_and_only_applies_to_direct_users(system):
    repository = system["repository"]
    app, org, branch = _app_tree(repository, "Acme", "acme")
    leaf = repository.create_org(app["id"], branch["id"], "Leaf")
    direct = repository.create_user(org_id=branch["id"], name="direct", password_hash=None)
    parent = repository.create_user(org_id=org["id"], name="parent", password_hash=None)
    child = repository.create_user(org_id=leaf["id"], name="child", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies")
    grant = repository.add_workspace_org(workspace["id"], org_id=branch["id"])
    assert grant["role"] == "viewer"
    newcomer = repository.create_user(org_id=branch["id"], name="newcomer", password_hash=None)
    for user in (direct, newcomer):
        assert repository.get_workspace_role(user, workspace["id"]) == "viewer"
    for user in (parent, child):
        assert repository.get_workspace_role(user, workspace["id"]) is None
    members = repository.list_workspace_members(workspace["id"])
    assert len(members) == 1
    assert {key: members[0][key] for key in ("id", "type", "org_id", "name", "role")} == {
        "id": grant["id"], "type": "org", "org_id": branch["id"], "name": branch["name"], "role": "viewer",
    }
    updated = repository.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    assert updated["id"] == grant["id"]
    assert repository.get_workspace_role(newcomer, workspace["id"]) == "editor"
    assert repository.update_workspace_org(workspace["id"], grant["id"], role="viewer")["role"] == "viewer"
    assert repository.get_workspace_role(direct, workspace["id"]) == "viewer"
    assert repository.delete_workspace_org(workspace["id"], grant["id"]) is True
    assert repository.get_workspace_role(newcomer, workspace["id"]) is None


def test_personal_viewer_overrides_org_editor_and_deletion_restores_org_role(system):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    user = repository.create_user(org_id=branch["id"], name="reader", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies")
    repository.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    member = repository.add_workspace_member(workspace["id"], user_id=user["id"], role="viewer")
    assert repository.get_workspace_role(user, workspace["id"]) == "viewer"
    rows = {row["type"]: row for row in repository.list_workspace_members(workspace["id"])}
    assert set(rows) == {"user", "org"}
    assert {key: rows["user"][key] for key in ("id", "user_id", "name", "role")} == {
        "id": member["id"], "user_id": user["id"], "name": user["name"], "role": "viewer",
    }
    assert repository.delete_workspace_member(workspace["id"], member["id"]) is True
    assert repository.get_workspace_role(user, workspace["id"]) == "editor"


@pytest.mark.parametrize("personal", [False, True], ids=["org-grant", "personal-grant"])
def test_workspace_role_tracks_transfers_and_rejects_cross_app_users(system, personal):
    repository = system["repository"]
    app, org, branch = _app_tree(repository, "Acme", "acme")
    _, other_org, _ = _app_tree(repository, "Other", "other")
    user = repository.create_user(org_id=branch["id"], name="moving", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies")
    repository.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    if personal:
        repository.add_workspace_member(workspace["id"], user_id=user["id"], role="viewer")
    expected = "viewer" if personal else "editor"
    assert repository.get_workspace_role(user, workspace["id"]) == expected
    repository.update_user(user["id"], org_id=org["id"])
    assert repository.get_workspace_role(user, workspace["id"]) == ("viewer" if personal else None)
    repository.update_user(user["id"], org_id=branch["id"])
    assert repository.get_workspace_role(user, workspace["id"]) == expected
    repository.update_user(user["id"], org_id=other_org["id"])
    repository.add_workspace_org(workspace["id"], org_id=other_org["id"], role="editor")
    assert repository.get_workspace_role(user, workspace["id"]) is None
    assert repository.has_workspace_access(user, workspace["id"]) is False


@pytest.mark.parametrize("personal", [False, True], ids=["org-grant", "personal-grant"])
@pytest.mark.parametrize("disabled", ["user", "department", "ancestor"])
def test_workspace_role_rechecks_disabled_users_and_org_ancestors(system, personal, disabled):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    leaf = repository.create_org(app["id"], branch["id"], "Leaf")
    user = repository.create_user(org_id=leaf["id"], name="member", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies")
    if personal:
        repository.add_workspace_member(workspace["id"], user_id=user["id"])
    else:
        repository.add_workspace_org(workspace["id"], org_id=leaf["id"], role="editor")
    assert repository.get_workspace_role(user, workspace["id"]) == "editor"
    if disabled == "user":
        repository.delete_user(user["id"])
    else:
        assert repository.delete_org(leaf["id"] if disabled == "department" else branch["id"]) is True
    # Keep the original user dict to verify that authorization reads current database state.
    assert repository.get_workspace_role(user, workspace["id"]) is None
    assert repository.has_workspace_access(user, workspace["id"]) is False


def _revoke_admin(repository, workspace_id, member, operation):
    if operation == "delete":
        return repository.delete_workspace_member(workspace_id, member["id"])
    if operation == "update":
        return repository.update_workspace_member(workspace_id, member["id"], role="viewer")
    return repository.add_workspace_member(workspace_id, user_id=member["user_id"], role="editor")


@pytest.mark.parametrize("creator_kind", ["owner", "org-user"])
@pytest.mark.parametrize("operation", ["delete", "update", "upsert"])
def test_creator_gets_personal_admin_and_last_admin_cannot_be_revoked(system, creator_kind, operation):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    creator = system["admin"] if creator_kind == "owner" else repository.create_user(
        org_id=branch["id"], name="creator", password_hash=None,
    )
    workspace = repository.create_workspace(app["id"], "Policies", creator_id=creator["id"])
    members = repository.list_workspace_members(workspace["id"])
    assert len(members) == 1
    assert members[0]["type"] == "user"
    assert members[0]["user_id"] == creator["id"]
    assert repository.get_workspace_role(creator, workspace["id"]) == "admin"
    with pytest.raises(ValueError, match="^Workspace must retain an administrator$"):
        _revoke_admin(repository, workspace["id"], members[0], operation)
    assert repository.list_workspace_members(workspace["id"]) == members
    assert repository.get_workspace_role(creator, workspace["id"]) == "admin"


@pytest.mark.parametrize("invalid_admin", ["disabled-user", "disabled-org", "disabled-ancestor", "cross-app"])
@pytest.mark.parametrize("operation", ["delete", "update", "upsert"])
def test_only_effective_personal_admins_count_for_last_admin_guard(system, invalid_admin, operation):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    leaf = repository.create_org(app["id"], branch["id"], "Leaf")
    user = repository.create_user(org_id=leaf["id"], name="other-admin", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    owner_member = repository.list_workspace_members(workspace["id"])[0]
    other_member = repository.add_workspace_member(workspace["id"], user_id=user["id"], role="admin")
    repository.add_workspace_org(workspace["id"], org_id=branch["id"], role="editor")
    if invalid_admin == "disabled-user":
        repository.delete_user(user["id"])
    elif invalid_admin == "disabled-org":
        assert repository.delete_org(leaf["id"]) is True
    elif invalid_admin == "disabled-ancestor":
        assert repository.delete_org(branch["id"]) is True
    else:
        _, other_org, _ = _app_tree(repository, "Other", "other")
        repository.update_user(user["id"], org_id=other_org["id"])
    assert repository.get_workspace_role(user, workspace["id"]) is None
    with pytest.raises(ValueError, match="^Workspace must retain an administrator$"):
        _revoke_admin(repository, workspace["id"], owner_member, operation)
    assert repository.get_workspace_role(system["admin"], workspace["id"]) == "admin"
    assert repository.delete_workspace_member(workspace["id"], other_member["id"]) is True


@pytest.mark.parametrize("operations", [
    ("delete", "delete"), ("update", "update"), ("upsert", "upsert"),
    ("delete", "update"), ("delete", "upsert"), ("update", "upsert"),
])
def test_concurrent_admin_revocations_retain_one_admin(system, monkeypatch, operations):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    user = repository.create_user(org_id=branch["id"], name="second-admin", password_hash=None)
    workspace = repository.create_workspace(app["id"], "Policies", creator_id=system["admin"]["id"])
    first = repository.list_workspace_members(workspace["id"])[0]
    second = repository.add_workspace_member(workspace["id"], user_id=user["id"], role="admin")
    ready = Barrier(2)
    lock_workspace = repository._lock_workspace

    def synchronized_lock(connection, workspace_id):
        connection.execute("SET LOCAL lock_timeout = '5s'")
        ready.wait(timeout=5)
        lock_workspace(connection, workspace_id)

    def revoke(member, operation):
        try:
            result = _revoke_admin(repository, workspace["id"], member, operation)
            assert result
            return "revoked"
        except ValueError as exc:
            assert str(exc) == "Workspace must retain an administrator"
            return "retained"

    monkeypatch.setattr(repository, "_lock_workspace", synchronized_lock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(revoke, member, operation) for member, operation in zip((first, second), operations)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["retained", "revoked"]
    members = repository.list_workspace_members(workspace["id"])
    assert sum(member["role"] == "admin" for member in members) == 1
    roles = [repository.get_workspace_role(actor, workspace["id"]) for actor in (system["admin"], user)]
    assert roles.count("admin") == 1


@pytest.mark.parametrize("role", ["admin", "owner", "member", "", None])
def test_org_grants_reject_invalid_roles_on_add_and_update(system, role):
    repository = system["repository"]
    app, _, branch = _app_tree(repository, "Acme", "acme")
    workspace = repository.create_workspace(app["id"], "Policies")
    grant = repository.add_workspace_org(workspace["id"], org_id=branch["id"])
    with pytest.raises(ValueError, match="^Invalid workspace role$"):
        repository.add_workspace_org(workspace["id"], org_id=branch["id"], role=role)
    with pytest.raises(ValueError, match="^Invalid workspace role$"):
        repository.update_workspace_org(workspace["id"], grant["id"], role=role)
    assert repository.list_workspace_members(workspace["id"])[0]["role"] == "viewer"


def test_list_orgs_returns_complete_app_tree_without_crossing_apps(system):
    repository = system["repository"]
    first, first_root, first_branch = _app_tree(repository, "First", "first")
    sibling = repository.create_org(first["id"], first_root["id"], "Sibling")
    leaf = repository.create_org(first["id"], first_branch["id"], "Leaf")
    _, second_root, _ = _app_tree(repository, "Second", "second")
    visible = repository.list_orgs(first_branch["id"])
    assert [org["id"] for org in visible] == [first_root["id"], first_branch["id"], sibling["id"], leaf["id"]]
    assert second_root["id"] not in {org["id"] for org in visible}
    repository.delete_org(first_branch["id"])
    assert [org["id"] for org in repository.list_orgs(leaf["id"])] == [first_root["id"], sibling["id"]]
    assert [org["id"] for org in repository.list_orgs(leaf["id"], include_disabled=True)] == [first_root["id"], first_branch["id"], sibling["id"], leaf["id"]]
    assert leaf["id"] not in {org["id"] for org in repository.list_orgs(None)}


def test_owner_lists_all_orgs_without_platform_root(system):
    repository = system["repository"]
    _, first_root, _ = _app_tree(repository, "First", "first")
    _, second_root, _ = _app_tree(repository, "Second", "second")
    assert {first_root["id"], second_root["id"]} <= {org["id"] for org in repository.list_orgs(None)}


def test_workspace_files_do_not_require_org_and_can_move_workspaces(system):
    repository = system["repository"]
    app, _, _ = _app_tree(repository, "Acme", "acme")
    source = repository.create_workspace(app["id"], "Source")
    target = repository.create_workspace(app["id"], "Target")
    record = repository.create_file(workspace_id=source["id"], filename="policy.txt", status="uploaded")
    assert "org_id" not in record
    assert repository.list_workspace_files(source["id"]) == [record]
    moved = repository.update_file(record["id"], workspace_id=target["id"], filename="renamed.txt")
    assert moved["workspace_id"] == target["id"]
    assert moved["filename"] == "renamed.txt"
    assert repository.list_workspace_files(source["id"]) == []
    assert repository.list_workspace_files(target["id"]) == [moved]
