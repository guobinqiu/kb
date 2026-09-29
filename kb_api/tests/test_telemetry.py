import asyncio
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from kb_api.api.main import _unhandled_exception
from kb_api.api import telemetry
from kb_api.api.middleware import install_request_id_middleware
from kb_api.api.telemetry import get_trace_id, install_search_tracing


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


def test_only_search_requests_export_spans(spans):
    provider, exporter = spans
    app = FastAPI()
    install_search_tracing(app, service_name="test", tracer_provider=provider)

    @app.post("/api/v1/rag/search")
    def search():
        return {"traceId": get_trace_id()}

    @app.get("/api/v1/files")
    def files():
        return {"traceId": get_trace_id()}

    with TestClient(app) as client:
        response = client.get("/api/v1/files", headers={"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"})
        assert response.headers["X-Trace-Id"] == response.json()["traceId"]
        assert "traceparent" not in response.headers
        assert exporter.get_finished_spans() == ()
        response = client.post("/api/v1/rag/search")
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "POST /api/v1/rag/search"
    assert response.json()["traceId"] == trace.format_trace_id(finished[0].context.trace_id)


def test_search_uses_incoming_trace(spans):
    provider, exporter = spans
    app = FastAPI()
    install_search_tracing(app, service_name="test", tracer_provider=provider)

    @app.post("/api/v1/rag/search")
    def endpoint():
        return {"traceId": get_trace_id()}

    with TestClient(app) as client:
        response = client.post("/api/v1/rag/search", headers={"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"})
    assert response.json()["traceId"] == "a" * 32
    assert response.headers["X-Trace-Id"] == "a" * 32
    server = exporter.get_finished_spans()[0]
    assert server.kind == trace.SpanKind.SERVER
    assert server.parent.span_id == int("b" * 16, 16)


def test_concurrent_search_requests_have_separate_traces(spans):
    provider, exporter = spans
    app = FastAPI()
    install_search_tracing(app, service_name="test", tracer_provider=provider)

    @app.post("/api/v1/rag/search")
    async def endpoint():
        before = get_trace_id()
        await asyncio.sleep(0)
        return {"before": before, "after": get_trace_id()}

    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            return await asyncio.gather(client.post("/api/v1/rag/search"), client.post("/api/v1/rag/search"))

    first, second = asyncio.run(requests())
    assert first.json()["before"] == first.json()["after"]
    assert second.json()["before"] == second.json()["after"]
    assert first.json()["before"] != second.json()["before"]
    assert len(exporter.get_finished_spans()) == 2


@pytest.mark.parametrize("path,exported", [("/api/v1/rag/search", True), ("/api/v1/files", False)])
def test_error_keeps_request_id_with_or_without_span(spans, path, exported):
    provider, exporter = spans
    app = FastAPI()
    app.add_exception_handler(Exception, _unhandled_exception)
    install_search_tracing(app, service_name="test", tracer_provider=provider)

    @app.post(path)
    def endpoint():
        raise RuntimeError("test failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path)
    assert response.status_code == 500
    assert response.headers["X-Trace-Id"] == response.json()["traceId"]
    finished = exporter.get_finished_spans()
    if exported:
        assert response.json()["traceId"] == trace.format_trace_id(finished[0].context.trace_id)
        assert finished[0].status.status_code == trace.StatusCode.ERROR
    else:
        assert finished == ()


def test_indexer_request_ids_do_not_initialize_telemetry(spans, monkeypatch):
    _, exporter = spans
    configure = Mock(side_effect=AssertionError("indexer must not initialize telemetry"))
    monkeypatch.setattr(telemetry, "configure_telemetry", configure)
    app = FastAPI()
    install_request_id_middleware(app, service_name="rag_indexer")

    @app.post("/api/v1/rag/search")
    def endpoint():
        return {"traceId": get_trace_id()}

    with TestClient(app) as client:
        response = client.post("/api/v1/rag/search")
    assert response.headers["X-Trace-Id"] == response.json()["traceId"]
    assert exporter.get_finished_spans() == ()
    configure.assert_not_called()


def test_safe_exporter_removes_exception_secrets_and_keeps_search_attributes():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(telemetry._SafeExporter(exporter)))
    secret = "PRIVATE_CREDENTIAL"
    try:
        with provider.get_tracer(__name__).start_as_current_span("rag.search", attributes={
            "app_id": "app", "workspace_ids": ["w1"], "model": "model", "top_k": 5,
            "http.url": f"https://user:{secret}@storage.example/file?signature={secret}",
            "query": secret,
        }) as span:
            span.record_exception(RuntimeError(secret))
            span.set_status(trace.Status(trace.StatusCode.ERROR, secret))
        exported = exporter.get_finished_spans()[0]
        assert secret not in exported.to_json()
        assert exported.attributes["top_k"] == 5
        assert exported.attributes["workspace_ids"] == ("w1",)
        assert exported.status.status_code == trace.StatusCode.ERROR
        assert exported.status.description is None
        assert dict(exported.events[0].attributes) == {"exception.type": "RuntimeError"}
    finally:
        provider.shutdown()


@pytest.mark.parametrize("general,specific,expected", [(None, None, 3.0), ("7", None, 7.0), ("7", "1.5", 1.5)])
def test_exporter_timeout_default_and_standard_environment(monkeypatch, general, specific, expected):
    for key, value in (("OTEL_EXPORTER_OTLP_TIMEOUT", general), ("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", specific)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    exporter = telemetry._create_otlp_exporter()
    try:
        assert exporter._timeout == expected
    finally:
        exporter.shutdown()


def test_exporter_failure_does_not_change_search_response(monkeypatch):
    exporter = Mock()
    exporter.export.side_effect = RuntimeError("collector unavailable")
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(telemetry._SafeExporter(exporter), schedule_delay_millis=60000))
    app = FastAPI()
    install_search_tracing(app, service_name="test", tracer_provider=provider)

    @app.post("/api/v1/rag/search")
    def endpoint():
        return {"results": []}

    try:
        with TestClient(app) as client:
            assert client.post("/api/v1/rag/search").json() == {"results": []}
        monkeypatch.setattr(telemetry.trace, "get_tracer_provider", lambda: provider)
        telemetry.flush_telemetry()
        exporter.export.assert_called_once()
        assert telemetry._SafeExporter(exporter).export([]) == SpanExportResult.FAILURE
    finally:
        provider.shutdown()
