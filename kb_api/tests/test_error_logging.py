from __future__ import annotations

import logging
import re

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from kb_api.api.main import create_app
from kb_api.rag_search.common.upstream import UpstreamServiceError

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class _FakeDao:
    def close(self):
        pass


class _FakeStorage:
    def close(self):
        pass


class _FakeQueue:
    def close(self):
        pass


class _FakeSearchService:
    def close(self):
        pass


@pytest.fixture
def error_client():
    app = create_app(
        dao=_FakeDao(),
        storage=_FakeStorage(),
        queue=_FakeQueue(),
        search_service=_FakeSearchService(),
        token_secret="test-secret",
        initialize=False,
    )

    @app.get("/__test__/http-503")
    def raise_http_503():
        raise HTTPException(status_code=503, detail="search backend unavailable")

    @app.get("/__test__/http-403")
    def raise_http_403():
        raise HTTPException(status_code=403, detail="not allowed here")

    @app.get("/__test__/http-409")
    def raise_http_409():
        raise HTTPException(status_code=409, detail="conflict detected")

    @app.get("/__test__/http-401")
    def raise_http_401():
        raise HTTPException(status_code=401, detail="authentication required")

    @app.get("/__test__/http-404")
    def raise_http_404():
        raise HTTPException(status_code=404, detail="resource missing")

    @app.get("/__test__/upstream-502")
    def raise_upstream():
        raise UpstreamServiceError(
            service="retriever", error="retriever exploded", retryable=True, status_code=502
        )

    @app.get("/__test__/validation-error")
    def validation_error(limit: int):
        return {"limit": limit}

    @app.get("/__test__/unhandled")
    def raise_unhandled():
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _kb_api_records(caplog):
    return [record for record in caplog.records if record.name == "kb_api"]


def test_http_503_logs_error_with_request_context(error_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get("/__test__/http-503")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["service"] == "kb_api"
    assert body["error"] == "search backend unavailable"
    assert body["retryable"] is True

    errors = [record for record in _kb_api_records(caplog) if record.levelno == logging.ERROR]
    assert errors, "expected an ERROR log record for HTTP 503"
    record = errors[0]
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == "/__test__/http-503"
    assert record.__dict__.get("status") == 503
    assert TRACE_ID_PATTERN.match(str(record.__dict__.get("trace_id") or ""))


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("/__test__/http-403", 403, "not allowed here"),
        ("/__test__/http-409", 409, "conflict detected"),
    ],
)
def test_http_client_error_logs_warning(error_client, caplog, path, status, detail):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get(path)

    assert response.status_code == status
    body = response.json()
    assert body["success"] is False
    assert body["service"] == "kb_api"
    assert body["error"] == detail
    assert body["retryable"] is False

    warnings = [record for record in _kb_api_records(caplog) if record.levelno == logging.WARNING]
    assert warnings, f"expected a WARNING log record for HTTP {status}"
    record = warnings[0]
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == path
    assert record.__dict__.get("status") == status


@pytest.mark.parametrize("path", ["/__test__/http-401", "/__test__/http-404"])
def test_http_401_404_logs_debug_only(error_client, caplog, path):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get(path)

    assert response.status_code in (401, 404)
    body = response.json()
    assert body["success"] is False
    assert body["retryable"] is False

    records = _kb_api_records(caplog)
    assert records, "expected a DEBUG log record for HTTP 401/404"
    assert all(record.levelno == logging.DEBUG for record in records)
    record = records[0]
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == path
    assert record.__dict__.get("status") in (401, 404)


def test_validation_error_422_logs_debug(error_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get("/__test__/validation-error", params={"limit": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["service"] == "kb_api"
    assert body["retryable"] is False

    records = _kb_api_records(caplog)
    assert records, "expected a DEBUG log record for RequestValidationError"
    assert all(record.levelno == logging.DEBUG for record in records)
    record = records[0]
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == "/__test__/validation-error"
    assert record.__dict__.get("status") == 422


def test_upstream_service_error_logs_error_with_detail(error_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get("/__test__/upstream-502")

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"error", "service", "retryable", "traceId"}
    assert body["error"] == "retriever exploded"
    assert body["service"] == "retriever"
    assert body["retryable"] is True
    assert TRACE_ID_PATTERN.match(body["traceId"])

    errors = [record for record in _kb_api_records(caplog) if record.levelno == logging.ERROR]
    assert errors, "expected an ERROR log record for UpstreamServiceError"
    record = errors[0]
    assert "retriever exploded" in record.getMessage()
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == "/__test__/upstream-502"


def test_unhandled_exception_still_logs_error(error_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="kb_api"):
        response = error_client.get("/__test__/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "kaboom"

    errors = [record for record in _kb_api_records(caplog) if record.levelno == logging.ERROR]
    assert errors, "expected the existing ERROR log record for unhandled exceptions"
    record = errors[0]
    assert record.__dict__.get("method") == "GET"
    assert record.__dict__.get("path") == "/__test__/unhandled"
    assert TRACE_ID_PATTERN.match(str(record.__dict__.get("trace_id") or ""))
