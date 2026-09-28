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


def has_workspace_permission(repository, user: dict, workspace: dict, operation: str) -> bool:
    role = repository.get_workspace_role(user, workspace["id"])
    return operation in WORKSPACE_ROLE_PERMISSIONS.get(role, ())


def can_manage_app(repository, user: dict, app_id: str) -> bool:
    if user["role"] == "owner":
        return True
    if user["role"] != "admin" or not user.get("org_id"):
        return False
    org = repository.get_org(user["org_id"])
    return bool(org and org["app_id"] == app_id)


def can_change_workspace_file(repository, user: dict, workspace: dict, record: dict) -> bool:
    role = repository.get_workspace_role(user, workspace["id"])
    return role == "admin" or (role == "editor" and record.get("created_by") == user["id"])


def workspace_permissions(repository, user: dict, workspace: dict) -> dict[str, bool]:
    role = repository.get_workspace_role(user, workspace["id"])
    allowed = WORKSPACE_ROLE_PERMISSIONS.get(role, ())
    return {operation: operation in allowed for operation in sorted(WORKSPACE_OPERATIONS)}
