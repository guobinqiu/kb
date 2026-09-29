from fastapi import HTTPException


WORKSPACE_CREATE = "workspace.create"
WORKSPACE_UPDATE = "workspace.update"
WORKSPACE_DELETE = "workspace.delete"
WORKSPACE_MEMBERS_MANAGE = "workspace.members.manage"
WORKSPACE_FILES_READ = "workspace.files.read"
WORKSPACE_FILES_UPLOAD = "workspace.files.upload"
WORKSPACE_FILES_DELETE = "workspace.files.delete"
WORKSPACE_SEARCH = "workspace.search"

WORKSPACE_OPERATIONS = frozenset({
    WORKSPACE_UPDATE, WORKSPACE_DELETE, WORKSPACE_MEMBERS_MANAGE,
    WORKSPACE_FILES_READ, WORKSPACE_FILES_UPLOAD,
    WORKSPACE_FILES_DELETE, WORKSPACE_SEARCH,
})
WORKSPACE_ROLE_PERMISSIONS = {
    "admin": WORKSPACE_OPERATIONS,
    "editor": frozenset({
        WORKSPACE_FILES_READ, WORKSPACE_FILES_UPLOAD,
        WORKSPACE_FILES_DELETE, WORKSPACE_SEARCH,
    }),
    "viewer": frozenset({WORKSPACE_FILES_READ, WORKSPACE_SEARCH}),
}


def has_workspace_permission(dao, user: dict, workspace: dict, operation: str) -> bool:
    role = dao.get_workspace_role(user, workspace["id"])
    if operation == WORKSPACE_DELETE:
        return _can_delete_workspace(user, workspace, role)
    return operation in WORKSPACE_ROLE_PERMISSIONS.get(role, ())


def _can_delete_workspace(user: dict, workspace: dict, role: str | None) -> bool:
    return user["role"] == "owner" or (role == "admin" and workspace.get("created_by") == user["id"])


def can_create_workspace(dao, user: dict, app_id: str) -> bool:
    if user["role"] == "owner":
        return True
    if user["role"] not in {"admin", "member"} or not user.get("org_id"):
        return False
    org = dao.get_org(user["org_id"])
    return bool(org and org["app_id"] == app_id)


def can_change_workspace_file(dao, user: dict, workspace: dict, record: dict) -> bool:
    role = dao.get_workspace_role(user, workspace["id"])
    return role == "admin" or (role == "editor" and record.get("created_by") == user["id"])


def workspace_permissions(dao, user: dict, workspace: dict) -> dict[str, bool]:
    role = dao.get_workspace_role(user, workspace["id"])
    allowed = WORKSPACE_ROLE_PERMISSIONS.get(role, ())
    permissions = {operation: operation in allowed for operation in sorted(WORKSPACE_OPERATIONS)}
    permissions[WORKSPACE_DELETE] = _can_delete_workspace(user, workspace, role)
    return permissions


def require_admin(dao, user: dict, target_org_id: str | None) -> None:
    if user["role"] == "owner":
        return
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator required")
    if not target_org_id or target_org_id not in dao.subtree_org_ids(user["org_id"]):
        raise HTTPException(status_code=403, detail="Org is outside visible scope")
