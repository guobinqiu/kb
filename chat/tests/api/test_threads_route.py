from types import SimpleNamespace

import pytest
from starlette.requests import Request


pytestmark = pytest.mark.unit


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/threads",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    })


@pytest.mark.asyncio
async def test_list_threads_returns_checkpointer_threads(monkeypatch):
    from chat.src.api.routes import threads

    class FakeCheckpointer:
        async def alist(self, config, *, limit=None):
            yield SimpleNamespace(
                config={"configurable": {"thread_id": "t1"}},
                checkpoint={"ts": "2026-09-07T10:00:00Z", "channel_values": {"messages": ["u", "a"]}},
            )
            yield SimpleNamespace(
                config={"configurable": {"thread_id": "t1"}},
                checkpoint={"ts": "2026-09-07T09:00:00Z", "channel_values": {"messages": ["u"]}},
            )
            yield SimpleNamespace(
                config={"configurable": {"thread_id": "t2"}},
                checkpoint={"ts": "2026-09-07T08:00:00Z", "channel_values": {"messages": ["u"]}},
            )

    monkeypatch.setattr(threads, "get_checkpointer", lambda: FakeCheckpointer())

    response = await threads.list_threads(_request())

    assert response.total == 2
    assert [thread.thread_id for thread in response.threads] == ["t1", "t2"]
    assert response.threads[0].message_count == 2
    assert response.threads[0].updated_at == "2026-09-07T10:00:00Z"
