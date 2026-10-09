from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
import psycopg
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long")
os.environ.setdefault("KB_ADMIN_PASSWORD", "admin-password")

from kb_api.api.auth import hash_password
from kb_api.api.main import create_app
from kb_api.api.rate_limit import _requests
from kb_api.api.dao import PostgresDAO


RESET_SQL = "TRUNCATE files, workspace_org, workspace_user, workspaces, users, orgs, apps RESTART IDENTITY CASCADE"


@dataclass
class FakeStorage:
    objects: dict[str, bytes] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    def presign_put(self, object_key: str, expires_seconds: int) -> str:
        return f"http://minio/{object_key}"

    def stat(self, s3_url: str):
        return SimpleNamespace(size=len(self.objects[s3_url]), content_type="text/plain")

    def checksum(self, s3_url: str) -> str:
        return hashlib.sha256(self.objects[s3_url]).hexdigest()

    def object_url(self, object_key: str) -> str:
        return f"s3://kb/{object_key}"

    def put(self, object_key: str, data: io.BytesIO, size: int, content_type: str | None) -> str:
        s3_url = self.object_url(object_key)
        self.objects[s3_url] = data.read()
        return s3_url

    def delete(self, s3_url: str) -> None:
        self.deleted.append(s3_url)
        self.objects.pop(s3_url, None)

    def close(self) -> None:
        pass


@dataclass
class FakeQueue:
    messages: list[tuple[str, dict]] = field(default_factory=list)
    closed: bool = False

    def publish(self, queue_name: str, message: dict) -> None:
        self.messages.append((queue_name, message))

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeSearchService:
    requests: list[dict] = field(default_factory=list)
    response: dict = field(default_factory=lambda: {"results": []})

    def search(self, request):
        self.requests.append({"json": request.model_dump(exclude_none=True)})
        return self.response

    def close(self) -> None:
        pass


@pytest.fixture
def system():
    _requests.clear()
    database_url = os.getenv("KB_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5432/rag_test")
    with psycopg.connect(database_url) as connection:
        database_name = connection.execute("SELECT current_database()").fetchone()[0]
    if not database_name.endswith("_test"):
        raise RuntimeError("KB_TEST_DATABASE_URL must point to a test database")
    dao = PostgresDAO(database_url)
    with dao._connect() as connection:
        connection.execute(RESET_SQL)
    admin = dao.create_user(
        org_id=None,
        name="admin",
        password_hash=hash_password("admin-password"),
        role="owner",
    )
    storage = FakeStorage()
    queue = FakeQueue()
    search_service = FakeSearchService()
    app = create_app(
        dao=dao,
        storage=storage,
        queue=queue,
        search_service=search_service,
        token_secret="test-secret-at-least-32-bytes-long",
        initialize=False,
    )
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"name": "admin", "password": "admin-password"},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            yield {
                "client": client,
                "dao": dao,
                "storage": storage,
                "queue": queue,
                "search_service": search_service,
                "admin": admin,
                "headers": {"Authorization": f"Bearer {token}"},
            }
    finally:
        with dao._connect() as connection:
            connection.execute(RESET_SQL)
