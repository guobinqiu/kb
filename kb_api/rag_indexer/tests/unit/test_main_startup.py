import signal
from types import SimpleNamespace

import pytest

import kb_api.rag_indexer.app.main as main
from kb_api.rag_indexer.common.config import parse_app_config
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient


pytestmark = pytest.mark.unit


def test_main_runs_consumer_and_closes_clients(monkeypatch):
    calls = []
    state = object()
    handlers = {}
    config = parse_app_config({
        "services": {"vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"}},
        "indexer": {"callback": {"url": "https://kb.example/api/v1/index-results", "timeout": 25}},
    })
    monkeypatch.setenv("RABBITMQ_URL", "amqp://rabbitmq")
    monkeypatch.setattr(main, "load_app_config", lambda: config)
    monkeypatch.setattr(main, "_build_state", lambda config: state)
    monkeypatch.setattr(main, "_close_clients", lambda value: calls.append(("close", value)))
    monkeypatch.setattr(main.signal, "signal", lambda name, handler: handlers.setdefault(name, handler))

    class Worker:
        def __init__(self, value, url, **kwargs):
            assert value is state
            assert url == "amqp://rabbitmq"
            assert kwargs["task_queue"] == "kb.index.tasks"
            assert kwargs["callback_url"] == "https://kb.example/api/v1/index-results"
            assert kwargs["callback_timeout"] == 25

        def run(self):
            calls.append("run")
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(main, "RabbitIndexWorker", Worker)
    main.main()
    assert calls == ["run", "stop", ("close", state)]


def test_main_closes_clients_when_consumer_fails(monkeypatch):
    state = object()
    closed = []
    monkeypatch.setenv("RABBITMQ_URL", "amqp://rabbitmq")
    monkeypatch.setattr(main, "load_app_config", lambda: SimpleNamespace(indexer=SimpleNamespace(
        callback=SimpleNamespace(url="http://kb/result", timeout=10),
    )))
    monkeypatch.setattr(main, "_build_state", lambda config: state)
    monkeypatch.setattr(main, "_close_clients", closed.append)
    monkeypatch.setattr(main.signal, "signal", lambda *args: None)

    class Worker:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            raise RuntimeError("consumer failed")

        def stop(self):
            pass

    monkeypatch.setattr(main, "RabbitIndexWorker", Worker)
    with pytest.raises(RuntimeError, match="consumer failed"):
        main.main()
    assert closed == [state]


def test_main_requires_mq_before_loading_components(monkeypatch):
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    with pytest.raises(ValueError, match="RABBITMQ_URL"):
        main.main()


def test_build_state_uses_local_components(monkeypatch):
    class Component:
        def __init__(self):
            self.dense = SimpleNamespace(vector_size=3, ready=True)
            self.started = False
            self.closed = False

        def start(self):
            self.started = True

        def close(self):
            self.closed = True

    parser = Component()
    inference = Component()
    monkeypatch.setattr(main, "_build_parser_client", lambda: parser)
    monkeypatch.setattr(main, "_build_inference_client", lambda: inference)
    config = parse_app_config({"services": {"vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"}}})
    state = main._build_state(config)
    assert state.parser_client is parser
    assert state.inference_client is inference
    assert parser.started
    assert isinstance(state.vector_client, QdrantVectorClient)
    main._close_clients(state)
    assert parser.closed and inference.closed


def test_close_clients_closes_in_dependency_order():
    calls = []
    state = SimpleNamespace(**{
        f"{name}_client": SimpleNamespace(close=lambda name=name: calls.append(name))
        for name in ("parser", "vector", "inference")
    })
    main._close_clients(state)
    assert calls == ["parser", "vector", "inference"]
