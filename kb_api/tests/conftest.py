from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
import psycopg
from fastapi.testclient import TestClient

from kb_api.auth import hash_password
from kb_api.main import create_app
from kb_api.rate_limit import _requests
from kb_api.repository import PostgresRepository


RESET_SQL = "TRUNCATE kb.files, kb.workspace_org, kb.workspace_user, kb.workspaces, kb.users, kb.orgs, kb.apps RESTART IDENTITY CASCADE"


@dataclass
class FakeStorage:
    objects: dict[str, bytes] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    def presign_put(self, object_key: str, expires_seconds: int) -> str:
        return f"http://minio/{object_key}"

    def stat(self, object_key: str):
        return SimpleNamespace(size=len(self.objects[object_key]), content_type="text/plain")

    def object_url(self, object_key: str) -> str:
        return f"s3://kb/{object_key}"

    def put(self, object_key: str, data: io.BytesIO, size: int, content_type: str | None) -> str:
        self.objects[object_key] = data.read()
        return f"s3://kb/{object_key}"

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    def close(self) -> None:
        pass


@dataclass
class FakeQueue:
    messages: list[tuple[str, dict]] = field(default_factory=list)
    callback: object | None = None
    started_queue: str | None = None
    closed: bool = False

    def publish(self, queue_name: str, message: dict) -> None:
        self.messages.append((queue_name, message))

    def start_consumer(self, queue_name: str, callback) -> None:
        self.started_queue = queue_name
        self.callback = callback

    def close(self) -> None:
        self.closed = True

    def deliver(self, message: dict) -> None:
        assert self.callback is not None
        self.callback(message)


@dataclass
class FakeRetriever:
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
    repository = PostgresRepository(database_url)
    with repository._connect() as connection:
        connection.execute(RESET_SQL)
    admin = repository.create_user(
        org_id=None,
        name="admin",
        password_hash=hash_password("admin-password"),
        role="owner",
    )
    storage = FakeStorage()
    queue = FakeQueue()
    retriever = FakeRetriever()
    app = create_app(
        repository=repository,
        storage=storage,
        queue=queue,
        retriever=retriever,
        token_secret="test-secret",
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
                "repository": repository,
                "storage": storage,
                "queue": queue,
                "retriever": retriever,
                "admin": admin,
                "headers": {"Authorization": f"Bearer {token}"},
            }
    finally:
        with repository._connect() as connection:
            connection.execute(RESET_SQL)
