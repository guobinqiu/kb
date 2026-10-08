"""RagClient 单测。"""

from __future__ import annotations

import json

import httpx
import pytest

from chat.src.rag.client import RagClient, get_rag_client


pytestmark = pytest.mark.unit


def _build_request(**client_kwargs):
    try:
        from chat.src.rag.client import RagClient
        from chat.src.rag.schemas import SearchRequest
    except Exception as exc:
        pytest.fail(f"rag.client / rag.schemas not importable: {exc}")
    app_id = client_kwargs.pop("app_id", "myapp")
    authorization = client_kwargs.pop("authorization", "Bearer test-api-key")
    return (
        _CredentialClient(RagClient(**client_kwargs), app_id, authorization),
        SearchRequest,
    )


class _CredentialClient:
    def __init__(
        self, client, app_id: str, authorization: str | None
    ):
        self._client = client
        self._app_id = app_id
        self._authorization = authorization

    async def search(self, req, **kwargs):
        kwargs.setdefault("app_id", self._app_id)
        kwargs.setdefault("authorization", self._authorization)
        return await self._client.search(req, **kwargs)

    async def aclose(self):
        await self._client.aclose()


@pytest.mark.asyncio
async def test_client_sends_bearer_auth_without_fabricated_traceparent(install_mock_transport):
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(
        base_url="http://rag.local:8000",
        app_id="my_app",
        authorization="Bearer my-api-key",
    )
    try:
        await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert len(captured) == 1
    headers = captured[0].headers
    assert headers.get("Authorization") == "Bearer my-api-key"
    # MockTransport bypasses automatic HTTP instrumentation; never synthesize a span ID.
    assert "traceparent" not in headers
    assert headers.get("Content-Type") == "application/json"
    assert "X-Workspace-Id" not in headers


@pytest.mark.asyncio
async def test_client_does_not_fabricate_identity_headers_without_authorization(install_mock_transport):
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)
    client, SearchRequest = _build_request(
        base_url="http://rag.local:8000",
        app_id="app-id",
        authorization=None,
    )
    try:
        await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    headers = captured[0].headers
    assert "Authorization" not in headers
    assert "X-Principal-Type" not in headers
    assert headers["X-App-Id"] == "app-id"
    assert "X-Workspace-Id" not in headers


@pytest.mark.asyncio
async def test_client_sends_exact_body_bytes_no_reserialize(install_mock_transport):
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local")
    try:
        req = SearchRequest(query="退款流程", workspace_ids=["workspace-1", "workspace-2"], top_k=3)
        await client.search(req)
    finally:
        await client.aclose()

    expected_bytes = json.dumps(
        req.model_dump(exclude_none=True),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert captured[0].content == expected_bytes


@pytest.mark.asyncio
async def test_client_url_is_base_url_plus_search_path(install_mock_transport):
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local:8000/")
    try:
        await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert str(captured[0].url).endswith("/api/v1/rag/search")
    assert "rag.local:8000/api/v1/rag/search" in str(captured[0].url)


@pytest.mark.asyncio
async def test_client_retries_on_5xx(install_mock_transport):
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="upstream unavailable")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local", max_retries=2)
    try:
        result = await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert call_count["n"] >= 2
    assert result.success is False
    assert result.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 422])
async def test_client_does_not_retry_on_client_error(install_mock_transport, status_code):
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(status_code, text="client error")

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local")
    try:
        result = await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert call_count["n"] == 1
    assert result.success is False
    assert result.status_code == status_code


@pytest.mark.asyncio
async def test_client_retries_on_timeout(install_mock_transport):
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectTimeout("simulated timeout")
        return httpx.Response(200, json={"results": [], "elapsed_ms": 1.0})

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local")
    try:
        result = await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert call_count["n"] == 2
    assert result.success is True


@pytest.mark.asyncio
async def test_client_5xx_then_recovery_succeeds(install_mock_transport):
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json={
                "results": [{"id": "c1", "content": "found"}],
                "elapsed_ms": 5.0,
            },
        )

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local")
    try:
        result = await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert result.success is True
    assert call_count["n"] >= 3
    assert len(result.documents) == 1
    assert result.documents[0].id == "c1"


@pytest.mark.asyncio
async def test_client_aclose_releases_resources():

    client = RagClient(base_url="http://rag.local")
    await client.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_get_rag_client_singleton_returns_same_instance():

    a = get_rag_client()
    b = get_rag_client()
    assert a is b
    assert hasattr(a, "aclose") and callable(a.aclose)


@pytest.mark.asyncio
async def test_result_documents_parsed_as_pydantic(install_mock_transport):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"id": "chunk-99", "content": "退 7 天"}],
                "elapsed_ms": 3.5,
            },
        )

    install_mock_transport(handler)

    client, SearchRequest = _build_request(base_url="http://rag.local")
    try:
        result = await client.search(SearchRequest(query="hi", workspace_ids=["workspace-1"]))
    finally:
        await client.aclose()

    assert result.success is True
    assert result.status_code == 200
    assert result.elapsed_ms == 3.5
    assert result.documents[0].id == "chunk-99"
