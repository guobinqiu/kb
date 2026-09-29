import pytest
from langgraph.checkpoint.memory import MemorySaver

from chat.src import main


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_create_checkpointer_falls_back_to_memory(monkeypatch):

    class FailingPool:
        check_connection = object()

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("postgres unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "AsyncConnectionPool", FailingPool)

    resource, checkpointer = await main._create_checkpointer()

    assert isinstance(checkpointer, MemorySaver)
    await resource.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_create_checkpointer_uses_checked_connection_pool(monkeypatch):

    events = []

    class WorkingPool:
        check_connection = object()

        def __init__(self, conninfo, **kwargs):
            self.conninfo = conninfo
            self.kwargs = kwargs

        async def __aenter__(self):
            events.append("pool enter")
            return self

        async def __aexit__(self, exc_type, exc, tb):
            events.append("pool exit")

        async def wait(self, timeout):
            events.append(("pool ready", timeout))

    class Saver:
        def __init__(self, conn):
            self.conn = conn

        async def setup(self):
            events.append("saver setup")

    monkeypatch.setattr(main, "AsyncConnectionPool", WorkingPool)
    monkeypatch.setattr(main, "AsyncPostgresSaver", Saver)

    resource, checkpointer = await main._create_checkpointer()

    assert checkpointer.conn.conninfo == main.settings.database_url
    assert checkpointer.conn.kwargs["check"] is WorkingPool.check_connection
    assert checkpointer.conn.kwargs["open"] is False
    assert checkpointer.conn.kwargs["kwargs"]["autocommit"] is True
    assert events == ["pool enter", ("pool ready", main.settings.request_timeout), "saver setup"]

    await resource.__aexit__(None, None, None)
    assert events[-1] == "pool exit"
