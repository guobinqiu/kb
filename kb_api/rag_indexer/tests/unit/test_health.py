from kb_api.rag_indexer.app.main import health


def test_rag_health_returns_ok():
    assert health() == {"status": "ok"}


def test_ready_without_relational_database_checks_core_services():
    from types import SimpleNamespace
    from kb_api.rag_indexer.core.api.services import health as service

    state = SimpleNamespace(
        ready=True,
        parser_client=SimpleNamespace(ready=True),
        inference_client=SimpleNamespace(ready=True),
        vector_client=SimpleNamespace(ready=True),
    )

    assert service.ready(state) == {"status": "ready"}


def test_ready_pings_required_dependencies(monkeypatch):
    from fastapi import HTTPException
    from kb_api.rag_indexer.core.api.services import health as service

    calls = []

    class Component:
        ready = True

        def __init__(self, name):
            self.name = name

        def ping(self):
            calls.append(self.name)
            return True

    state = type(
        "State",
        (),
        {
            "ready": True,
            "parser_client": Component("parser"),
            "inference_client": Component("inference"),
            "vector_client": Component("vector"),
        },
    )()
    assert service.ready(state) == {"status": "ready"}

    assert calls == ["parser", "inference", "vector"]
