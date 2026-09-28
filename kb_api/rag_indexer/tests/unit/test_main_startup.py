import pytest
from fastapi import FastAPI

from kb_api.rag_indexer.common.config import parse_app_config
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient


pytestmark = pytest.mark.unit


def test_indexer_keeps_request_ids():
    import runpy
    from fastapi.testclient import TestClient
    import kb_api.rag_indexer.app.main as main

    app = runpy.run_path(main.__file__)["app"]
    client = TestClient(app)
    first = client.get("/health")
    second = client.post("/api/v1/rag/search")

    assert first.status_code == 200
    assert len(first.headers["x-trace-id"]) == 32
    assert len(second.headers["x-trace-id"]) == 32
    assert first.headers["x-trace-id"] != second.headers["x-trace-id"]
    assert "traceparent" not in first.headers
    assert "traceparent" not in second.headers


def test_required_component_status_has_no_disabled_state(monkeypatch):
    from kb_api.rag_indexer.core.api.services import common as service

    class StoppedComponent:
        ready = False

    assert service.required_component_status(StoppedComponent()) == "error"
    assert service.required_component_status(StoppedComponent(), error="failed") == "error"


def test_lifespan_wires_clients(monkeypatch):
    import asyncio

    class VectorClient:
        def __init__(self):
            self.initialized = []

        def ensure_app_collection(self, app_id):
            self.initialized.append(app_id)

    calls = []
    vector = VectorClient()

    import kb_api.rag_indexer.app.main as main

    config = type("Config", (), {})()

    def configure_app(app, config):
        calls.append("configure")
        app.state.config = config
        app.state.vector_client = vector

    def close_clients(app):
        calls.append("close")

    monkeypatch.setattr(main, "_configure_app", configure_app)
    monkeypatch.setattr(main, "_close_clients", close_clients)
    monkeypatch.setattr(main, "_start_index_worker", lambda app: None)
    monkeypatch.setattr(main, "load_app_config", lambda: config)

    async def run_lifespan():
        app = FastAPI()
        async with main.lifespan(app):
            assert app.state.config is config

    asyncio.run(run_lifespan())
    assert calls == ["configure", "close"]
    assert vector.initialized == []


def test_lifespan_starts_and_stops_index_worker(monkeypatch):
    import asyncio
    import kb_api.rag_indexer.app.main as main

    calls = []
    config = type("Config", (), {})()
    worker = type("Worker", (), {"stop": lambda self: calls.append("stop")})()
    monkeypatch.setattr(main, "load_app_config", lambda: config)
    def configure_app(app, value):
        calls.append("configure")
        app.state.config = value

    monkeypatch.setattr(main, "_configure_app", configure_app)
    monkeypatch.setattr(main, "_start_index_worker", lambda app: calls.append("start") or worker)
    monkeypatch.setattr(main, "_close_clients", lambda app: calls.append("close"))

    async def run_lifespan():
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(run_lifespan())

    assert calls == ["configure", "start", "stop", "close"]


def test_configure_app_uses_local_components(monkeypatch):
    import kb_api.rag_indexer.app.main as main
    class Dense:
        vector_size = 3
        ready = True

    class Component:
        def __init__(self):
            self.dense = Dense()
            self.sparse = None
            self.rerank = None
            self.started = False

        def start(self):
            self.started = True

        def close(self):
            pass

        def ping(self):
            return True

    parser = Component()
    inference = Component()
    monkeypatch.setattr(main, "_build_parser_client", lambda: parser)
    monkeypatch.setattr(main, "_build_inference_client", lambda: inference)

    config = parse_app_config({
        "services": {
            "vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"},
        },
    })

    app = FastAPI()
    main._configure_app(app, config)

    assert app.state.parser_client is parser
    assert app.state.inference_client is inference
    assert parser.started is True
    assert isinstance(app.state.vector_client, QdrantVectorClient)
    main._close_clients(app)


def test_close_clients_closes_in_dependency_order():
    import kb_api.rag_indexer.app.main as main

    calls = []
    app = FastAPI()

    class Client:
        def __init__(self, name):
            self.name = name

        def close(self):
            calls.append(self.name)

    app.state.parser_client = Client("parser")
    app.state.vector_client = Client("vector")
    app.state.inference_client = Client("inference")
    app.state.ready = True

    main._close_clients(app)

    assert calls == ["parser", "vector", "inference"]
    assert app.state.ready is False
