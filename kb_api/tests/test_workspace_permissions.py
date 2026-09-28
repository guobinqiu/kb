from types import SimpleNamespace

from kb_api.permissions import (
    WORKSPACE_FILES_UPLOAD,
    WORKSPACE_UPDATE,
    can_change_workspace_file,
    has_workspace_permission,
)


def repository_with_role(role):
    return SimpleNamespace(
        get_workspace_role=lambda user, workspace_id: role,
        has_workspace_access=lambda user, workspace_id: role is not None,
        get_org=lambda org_id: {"app_id": "enterprise"},
    )


def test_enterprise_admin_without_membership_cannot_manage_workspace():
    user = {"id": "user", "role": "admin", "org_id": "org"}
    assert not has_workspace_permission(repository_with_role(None), user, {"id": "ws", "app_id": "enterprise"}, WORKSPACE_UPDATE)


def test_workspace_admin_does_not_require_enterprise_admin_role():
    user = {"id": "user", "role": "member", "org_id": "org"}
    assert has_workspace_permission(repository_with_role("admin"), user, {"id": "ws", "app_id": "enterprise"}, WORKSPACE_UPDATE)


def test_viewer_cannot_upload_or_delete_previously_owned_file():
    user = {"id": "user", "role": "member", "org_id": "org"}
    workspace = {"id": "ws", "app_id": "enterprise"}
    repository = repository_with_role("viewer")
    assert not has_workspace_permission(repository, user, workspace, WORKSPACE_FILES_UPLOAD)
    assert not can_change_workspace_file(repository, user, workspace, {"created_by": "user"})
