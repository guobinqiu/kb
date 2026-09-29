from types import SimpleNamespace

import pytest

from kb_api.api.permissions import (
    WORKSPACE_FILES_UPLOAD,
    WORKSPACE_DELETE,
    WORKSPACE_UPDATE,
    can_change_workspace_file,
    has_workspace_permission,
    workspace_permissions,
)


def dao_with_role(role):
    return SimpleNamespace(
        get_workspace_role=lambda user, workspace_id: role,
        has_workspace_access=lambda user, workspace_id: role is not None,
        get_org=lambda org_id: {"app_id": "enterprise"},
    )


def test_enterprise_admin_without_membership_cannot_manage_workspace():
    user = {"id": "user", "role": "admin", "org_id": "org"}
    assert not has_workspace_permission(dao_with_role(None), user, {"id": "ws", "app_id": "enterprise"}, WORKSPACE_UPDATE)


def test_workspace_admin_does_not_require_enterprise_admin_role():
    user = {"id": "user", "role": "member", "org_id": "org"}
    assert has_workspace_permission(dao_with_role("admin"), user, {"id": "ws", "app_id": "enterprise"}, WORKSPACE_UPDATE)


def test_viewer_cannot_upload_or_delete_previously_owned_file():
    user = {"id": "user", "role": "member", "org_id": "org"}
    workspace = {"id": "ws", "app_id": "enterprise"}
    dao = dao_with_role("viewer")
    assert not has_workspace_permission(dao, user, workspace, WORKSPACE_FILES_UPLOAD)
    assert not can_change_workspace_file(dao, user, workspace, {"created_by": "user"})


@pytest.mark.parametrize("platform_role,workspace_role,creator,expected", [
    ("member", "admin", "user", True),
    ("member", "admin", "other", False),
    ("admin", "admin", "other", False),
    ("member", "editor", "user", False),
    ("member", "viewer", "user", False),
    ("owner", None, "other", True),
    ("member", "admin", None, False),
])
def test_workspace_deletion_requires_owner_or_admin_creator(platform_role, workspace_role, creator, expected):
    user = {"id": "user", "role": platform_role}
    workspace = {"id": "ws", "created_by": creator}
    dao = dao_with_role(workspace_role)
    assert has_workspace_permission(dao, user, workspace, WORKSPACE_DELETE) is expected
    assert workspace_permissions(dao, user, workspace)[WORKSPACE_DELETE] is expected
