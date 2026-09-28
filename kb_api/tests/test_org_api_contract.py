import pytest
from pydantic import ValidationError
from types import SimpleNamespace
from fastapi.testclient import TestClient

from kb_api.api.routes.apps import create_app as create_app_route, list_apps as list_apps_route
from kb_api.api.routes.users import create_user as create_user_route, list_users as list_users_route
from kb_api.api.routes.workspaces import add_member as add_workspace_member_route
from kb_api.api.schemas import AppCreate, UserCreate, WorkspaceMemberCreate
from kb_api.auth import create_token, resolve_principal
from kb_api.main import app, create_app


def test_user_payload_uses_org_id_and_owner_has_no_org():
    member = UserCreate.model_validate({
        "org_id": "org-1",
        "name": "member",
        "password": "password-123",
    })
    assert member.org_id == "org-1"

    owner = UserCreate.model_validate({
        "name": "owner",
        "password": "password-123",
        "role": "owner",
    })
    assert owner.org_id is None

    with pytest.raises(ValidationError):
        UserCreate.model_validate({
            "node_id": "node-1",
            "name": "legacy",
            "password": "password-123",
        })


def test_workspace_member_payload_uses_typed_subject_and_role():
    payload = {"type": "user", "id": "user-1", "role": "admin"}
    assert WorkspaceMemberCreate.model_validate(payload).model_dump() == payload
    with pytest.raises(ValidationError):
        WorkspaceMemberCreate.model_validate({"node_id": "node-1"})
    with pytest.raises(ValidationError):
        WorkspaceMemberCreate.model_validate({"org_id": "org-1"})


def test_org_routes_replace_legacy_node_routes():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/orgs" in paths
    assert "/api/v1/orgs/{org_id}" in paths
    assert not any(path.startswith("/api/v1/nodes") for path in paths)


def test_search_only_exposes_rag_endpoint():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/rag/search" in paths
    assert "/api/v1/workspaces/{workspace_id}/search" not in paths


class _AuthRepository:
    def __init__(self, user):
        self.user = user
        self.active_org_calls = []

    def get_user(self, user_id):
        return self.user if user_id == self.user["id"] else None

    def is_active_org(self, org_id):
        self.active_org_calls.append(org_id)
        return True

    def get_org(self, org_id):
        return {"id": org_id, "app_id": "app-uuid"}

    def get_app(self, app_id):
        return {"id": app_id, "app_id": "business-app"}


def _request_for(user):
    secret = "test-secret"
    repository = _AuthRepository(user)
    request = SimpleNamespace(
        headers={"Authorization": f"Bearer {create_token({'sub': user['id']}, secret)}"},
        app=SimpleNamespace(state=SimpleNamespace(repository=repository, token_secret=secret)),
    )
    return request, repository


def test_owner_principal_has_no_org_and_does_not_check_org_activity():
    request, repository = _request_for({
        "id": "owner-1", "org_id": None, "role": "owner", "deleted_at": None,
    })

    principal = resolve_principal(request)

    assert principal["org_id"] is None
    assert "node_id" not in principal
    assert repository.active_org_calls == []


def test_member_principal_uses_active_org_context():
    request, repository = _request_for({
        "id": "member-1", "org_id": "org-1", "role": "member", "deleted_at": None,
    })

    principal = resolve_principal(request)

    assert principal["org_id"] == "org-1"
    assert principal["app_id"] == "business-app"
    assert repository.active_org_calls == ["org-1"]


class _AppRepository:
    def __init__(self):
        self.list_calls = []

    def list_apps(self, org_id, include_disabled=False):
        self.list_calls.append((org_id, include_disabled))
        return [{"id": "app-1", "app_id": "app", "api_key": "secret"}]

    def get_app_by_business_id(self, app_id):
        return None

    def create_app(self, name, app_id):
        return (
            {"id": "app-1", "app_id": app_id, "name": name},
            {"id": "org-1", "app_id": "app-1", "parent_id": None, "name": name},
        )


def test_owner_app_list_is_global_and_app_create_returns_org():
    repository = _AppRepository()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository)))
    owner = {"id": "owner-1", "org_id": None, "role": "owner"}

    assert list_apps_route(request, user=owner)["apps"][0]["id"] == "app-1"
    assert repository.list_calls == [(None, True)]
    created = create_app_route(AppCreate(app_id="acme", name="Acme"), request, user=owner)
    assert set(created) == {"app", "org"}
    assert created["org"]["parent_id"] is None


class _UserRepository:
    def __init__(self):
        self.list_calls = []
        self.create_values = None

    def list_users(self, org_id, include_disabled=False):
        self.list_calls.append((org_id, include_disabled))
        return []

    def create_user(self, **values):
        self.create_values = values
        return {"id": "owner-2", **values}


def test_owner_user_list_is_global_and_created_owner_has_null_org():
    repository = _UserRepository()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository)))
    owner = {"id": "owner-1", "org_id": None, "role": "owner"}

    assert list_users_route(request, include_disabled=True, user=owner) == {"users": []}
    created = create_user_route(UserCreate(
        name="owner-2", password="password-123", role="owner",
    ), request, user=owner)

    assert repository.list_calls == [(None, True)]
    assert created["org_id"] is None
    assert repository.create_values["org_id"] is None


class _NoopService:
    def start_consumer(self, *_args):
        pass

    def close(self):
        pass


class _MainRepository:
    def __init__(self):
        self.owner = {
            "id": "owner-1",
            "org_id": None,
            "name": "owner",
            "password_hash": None,
            "role": "owner",
            "deleted_at": None,
        }

    def get_user_by_name(self, name):
        return self.owner if name == "owner" else None

    def get_user(self, user_id):
        return self.owner if user_id == self.owner["id"] else None

    def list_apps(self, org_id, include_disabled=False):
        assert org_id is None
        return [{"id": "app-uuid", "app_id": "business-app"}]

    def get_app_by_api_key(self, _api_key):
        return None

    def close(self):
        pass


def test_owner_auth_context_uses_org_header_and_never_node_header(monkeypatch):
    repository = _MainRepository()
    application = create_app(
        repository=repository,
        storage=_NoopService(),
        queue=_NoopService(),
        retriever=SimpleNamespace(),
        token_secret="test-secret",
        initialize=False,
    )
    monkeypatch.setattr("kb_api.main.verify_password", lambda password, encoded: password == "password-123")

    with TestClient(application) as client:
        login = client.post("/api/v1/auth/login", json={"name": "owner", "password": "password-123"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert login.json()["user"]["org_id"] is None
        assert client.get("/api/v1/auth/me", headers=headers).json()["org_id"] is None
        verified = client.get(
            "/api/v1/auth/verify",
            headers=headers | {"X-App-Id": "business-app"},
        )

    assert verified.status_code == 200
    assert verified.headers["X-Org-Id"] == ""
    assert "X-Node-Id" not in verified.headers
    assert "node_id" not in verified.json()


class _WorkspaceRepository:
    def __init__(self):
        self.add_values = None

    def get_workspace(self, workspace_id):
        return {"id": workspace_id, "app_id": "app-1"}

    def has_workspace_access(self, user, workspace_id):
        return True

    def get_workspace_role(self, user, workspace_id):
        return "admin"

    def get_user(self, user_id):
        if not user_id:
            return None
        return {
            "id": user_id, "org_id": "org-1", "role": "member", "deleted_at": None,
        }

    def get_org(self, org_id):
        return {"id": org_id, "app_id": "app-1"}

    def is_active_org(self, org_id):
        return True

    def add_workspace_member(self, workspace_id, *, user_id, role):
        value = {"workspace_id": workspace_id, "user_id": user_id, "role": role}
        if self.add_values is None:
            self.add_values = []
        self.add_values.append(value)
        return {"id": f"membership-{user_id}", **value}

def test_workspace_member_api_persists_personal_role():
    repository = _WorkspaceRepository()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository)))
    owner = {"id": "owner-1", "org_id": None, "role": "owner"}

    result = add_workspace_member_route(
        "workspace-1", WorkspaceMemberCreate(type="user", id="user-1", role="editor"), request, user=owner,
    )

    assert result == {"member": {
        "id": "membership-user-1", "workspace_id": "workspace-1", "user_id": "user-1", "role": "editor",
    }}
    assert repository.add_values == [{"workspace_id": "workspace-1", "user_id": "user-1", "role": "editor"}]
