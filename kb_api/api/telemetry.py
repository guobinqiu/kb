from __future__ import annotations

import logging
import os
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from kb_api.api.middleware import get_request_id, install_request_id_middleware

_provider_lock = Lock()
logger = logging.getLogger(__name__)

_SAFE_ATTRIBUTES = {
    "http.method", "http.route", "http.status_code", "http.scheme",
    "http.request.method", "http.response.status_code", "url.scheme",
    "server.address", "server.port", "net.peer.name", "net.peer.port",
    "network.protocol.version", "error.type",
    "app_id", "workspace_id", "file_id", "service", "backend",
    "model", "mode", "top_k", "limit", "rerank", "rerank_fetch_k", "rrf_k",
    "input_count", "result_count", "vector_count", "dense_count", "sparse_count",
}


def _safe_url(value: str) -> str:
    try:
        url = urlsplit(value)
        return urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
    except ValueError:
        return ""


class _SafeExporter(SpanExporter):
    """Export operational attributes without payloads or exception text."""

    def __init__(self, exporter: SpanExporter):
        self.exporter = exporter

    def export(self, spans):
        try:
            safe_spans = []
            for span in spans:
                source = span.attributes or {}
                attributes = {
                    key: value for key, value in source.items()
                    if key in _SAFE_ATTRIBUTES and isinstance(value, (str, bool, int, float))
                }
                workspace_ids = source.get("workspace_ids")
                if isinstance(workspace_ids, (list, tuple)) and all(isinstance(value, str) for value in workspace_ids):
                    attributes["workspace_ids"] = workspace_ids
                for key in ("http.url", "url.full", "http.target"):
                    if isinstance(source.get(key), str):
                        attributes[key] = _safe_url(source[key])
                events = [
                    Event("exception", {"exception.type": (event.attributes or {}).get("exception.type", "Exception")}, timestamp=event.timestamp)
                    for event in span.events if event.name == "exception"
                ]
                safe_spans.append(ReadableSpan(
                    name=span.name, context=span.context, parent=span.parent,
                    resource=Resource({
                        key: value for key, value in span.resource.attributes.items()
                        if key in {"service.name", "service.version", "deployment.environment.name"}
                    }),
                    attributes=attributes, events=events, kind=span.kind,
                    status=trace.Status(span.status.status_code),
                    start_time=span.start_time, end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                ))
            return self.exporter.export(safe_spans)
        except Exception:
            logger.warning("Trace export failed")
            return SpanExportResult.FAILURE

    def shutdown(self):
        self.exporter.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.exporter.force_flush(timeout_millis)


def _create_otlp_exporter() -> OTLPSpanExporter:
    configured_timeout = any(key in os.environ for key in (
        "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", "OTEL_EXPORTER_OTLP_TIMEOUT",
    ))
    return OTLPSpanExporter(timeout=None if configured_timeout else 3.0)


def configure_telemetry(service_name: str) -> TracerProvider:
    with _provider_lock:
        existing = trace.get_tracer_provider()
        if isinstance(existing, TracerProvider):
            return existing
        provider = TracerProvider(resource=Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
        }))
        if os.getenv("OTEL_SDK_DISABLED", "false").lower() != "true" and (
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        ):
            provider.add_span_processor(BatchSpanProcessor(_SafeExporter(_create_otlp_exporter())))
        trace.set_tracer_provider(provider)
        return provider


def flush_telemetry() -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        # Best effort: SDK flush may wait for multiple exports; this is not a hard deadline.
        try:
            provider.force_flush()
        except Exception:
            logger.warning("Trace flush failed")


def get_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return trace.format_trace_id(span_context.trace_id)
    return get_request_id()


class _SearchTraceMiddleware:
    def __init__(self, app, *, tracer):
        self.app = app
        self.tracer = tracer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("method") != "POST" or scope.get("path") != "/api/v1/rag/search":
            return await self.app(scope, receive, send)
        carrier = {key.decode(): value.decode() for key, value in scope.get("headers", [])}
        with self.tracer.start_as_current_span(
            "POST /api/v1/rag/search",
            context=propagate.extract(carrier),
            kind=trace.SpanKind.SERVER,
            attributes={"http.request.method": "POST", "http.route": "/api/v1/rag/search"},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            await self._request(scope, receive, send, span)

    async def _request(self, scope, receive, send, span):
        state = scope.setdefault("state", {})
        span_context = span.get_span_context()
        if span_context.is_valid:
            state["trace_id"] = trace.format_trace_id(span_context.trace_id)
            headers = {}
            propagate.inject(headers)
            state["traceparent"] = headers.get("traceparent")

        async def send_response(message):
            if message["type"] == "http.response.start":
                span.set_attribute("http.response.status_code", message["status"])
                if message["status"] >= 500:
                    span.set_status(trace.StatusCode.ERROR)
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR)
            span.set_attribute("http.response.status_code", 500)
            span.set_attribute("error.type", type(exc).__name__)
            span.add_event("exception", {"exception.type": type(exc).__name__})
            raise


def install_search_tracing(app, *, service_name: str, tracer_provider=None) -> None:
    install_request_id_middleware(app, service_name=service_name)
    provider = tracer_provider or configure_telemetry(service_name)
    app.add_middleware(_SearchTraceMiddleware, tracer=provider.get_tracer(__name__))
