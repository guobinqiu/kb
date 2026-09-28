"""Tests for rag/ — local fixtures for httpx mocking.

These fixtures install an httpx.MockTransport-backed factory that intercepts
all AsyncClient construction inside rag.client, regardless of import style:

  import httpx                 # patched via monkeypatch.setattr on "httpx.AsyncClient"
  from httpx import AsyncClient # patched via setattr on rag.client.AsyncClient
  import httpx  as alias        # patched via setattr on rag.client.<attr>.AsyncClient
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest


@pytest.fixture
def install_mock_transport(monkeypatch) -> Callable:
    """Return an install(handler) helper that injects MockTransport into
    `httpx.AsyncClient` regardless of how rag.client imports it.

    Usage::

        def test_x(install_mock_transport):
            captured = []

            async def handler(request: httpx.Request) -> httpx.Response:
                captured.append(request)
                return httpx.Response(200, json={"results": []})

            install_mock_transport(handler)
            # now any `httpx.AsyncClient(...)` constructed inside rag.client
            # will route through the mock handler
    """
    real_async_client = httpx.AsyncClient

    def installer(handler):
        transport = httpx.MockTransport(handler)

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_async_client(*args, **kwargs)

        # Patch 1: module-level httpx.AsyncClient (covers "import httpx; httpx.AsyncClient(...)")
        monkeypatch.setattr("httpx.AsyncClient", factory)

        # Patch 2 & 3: defer to test-time import so collection doesn't fail
        try:
            import chat.src.rag.client as _rc_mod  # type: ignore
        except Exception:
            return  # rag.client doesn't exist yet; tests will fail naturally

        if hasattr(_rc_mod, "AsyncClient"):
            monkeypatch.setattr(_rc_mod, "AsyncClient", factory)
        if hasattr(_rc_mod, "httpx") and hasattr(_rc_mod.httpx, "AsyncClient"):
            monkeypatch.setattr(_rc_mod.httpx, "AsyncClient", factory)

    return installer


@pytest.fixture
def make_rag_client():
    """Build a RagClient with given kwargs, falling back to the no-impl RED state."""
    def _factory(**kwargs):
        try:
            from chat.src.rag.client import RagClient  # type: ignore
        except Exception as exc:
            pytest.fail(f"rag.client.RagClient not implemented — RED ({exc})")
        return RagClient(**kwargs)
    return _factory


@pytest.fixture
def fake_search_result():
    """Build a RagResult via the new schema, with sensible defaults."""
    def _factory(**overrides):
        try:
            from chat.src.rag.client import RagResult  # type: ignore
        except Exception:
            # Build a plain dataclass-compatible shim with the same fields
            from dataclasses import dataclass, field
            @dataclass
            class _R:
                success: bool = True
                status_code: int = 200
                documents: list = field(default_factory=list)
                elapsed_ms: float = 0.0
                raw: dict = field(default_factory=dict)
                error: str = ""
            r = _R()
        else:
            r = RagResult()

        for k, v in overrides.items():
            setattr(r, k, v)
        return r
    return _factory


@pytest.fixture
def fake_document():
    """Build a Document via the new schema (or skip if not implemented)."""
    def _factory(**kwargs):
        try:
            from chat.src.rag.schemas import Document  # type: ignore
        except Exception as exc:
            pytest.fail(f"rag.schemas.Document not implemented — RED ({exc})")
        defaults = {
            "id": "chunk-001",
            "content": "退款 7 天。",
        }
        defaults.update(kwargs)
        return Document(**defaults)
    return _factory
