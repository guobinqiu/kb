from types import SimpleNamespace

import pytest
from starlette.requests import Request

from chat.src.api.auth import Principal, scoped_thread_id
from chat.src.api.routes import threads


pytestmark = pytest.mark.unit


def _request() -> Request:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/llm/threads",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    })
    request.state.principal = Principal(type="user", app_id="acme", user_id="user-1")
    return request


def test_thread_routes_use_public_llm_prefix():
    paths = {route.path for route in threads.router.routes}

    assert "/api/v1/llm/threads" in paths
    assert "/api/v1/llm/threads/{thread_id}" in paths
    assert "/api/v1/llm/threads/{thread_id}/messages" in paths


@pytest.mark.asyncio
async def test_list_threads_returns_checkpointer_threads(monkeypatch):

    class FakeCheckpointer:
        async def alist(self, config, *, filter=None, limit=None):
            assert filter == {
                "app_id": "acme",
                "principal_type": "user",
                "principal_id": "user-1",
            }
            yield SimpleNamespace(
                config={"configurable": {"thread_id": scoped_thread_id(_request().state.principal, "t1")}},
                metadata={"external_thread_id": "t1"},
                checkpoint={"ts": "2026-09-07T10:00:00Z", "channel_values": {"messages": ["u", "a"]}},
            )
            yield SimpleNamespace(
                config={"configurable": {"thread_id": scoped_thread_id(_request().state.principal, "t1")}},
                metadata={"external_thread_id": "t1"},
                checkpoint={"ts": "2026-09-07T09:00:00Z", "channel_values": {"messages": ["u"]}},
            )
            yield SimpleNamespace(
                config={"configurable": {"thread_id": scoped_thread_id(_request().state.principal, "t2")}},
                metadata={"external_thread_id": "t2"},
                checkpoint={"ts": "2026-09-07T08:00:00Z", "channel_values": {"messages": ["u"]}},
            )

    monkeypatch.setattr(threads, "get_checkpointer", lambda: FakeCheckpointer())

    response = await threads.list_threads(_request())

    assert response.total == 2
    assert [thread.thread_id for thread in response.threads] == ["t1", "t2"]
    assert response.threads[0].message_count == 2
    assert response.threads[0].updated_at == "2026-09-07T10:00:00Z"


@pytest.mark.asyncio
async def test_get_history_uses_scoped_thread_id():
    request = _request()
    observed = []

    class FakeGraph:
        async def aget_state(self, config):
            observed.append(config)
            return SimpleNamespace(values={})

    response = await threads.get_history(request, "t1", graph=FakeGraph())

    assert observed == [{"configurable": {"thread_id": scoped_thread_id(request.state.principal, "t1")}}]
    assert response == {"thread_id": "t1", "messages": []}


@pytest.mark.asyncio
async def test_delete_thread_uses_scoped_thread_id(monkeypatch):
    request = _request()
    observed = []

    class FakeCheckpointer:
        async def adelete_thread(self, thread_id):
            observed.append(thread_id)

    monkeypatch.setattr(threads, "get_checkpointer", lambda: FakeCheckpointer())

    response = await threads.delete_thread(request, "t1")

    assert observed == [scoped_thread_id(request.state.principal, "t1")]
    assert response == {"deleted": True, "thread_id": "t1"}
