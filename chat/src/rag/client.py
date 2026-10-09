"""rag/client.py: 转发用户 Bearer + httpx 的 RAG 客户端。

公共 API：
    RagClient(...)                  — 单 client，可 aclose()
    get_rag_client() -> RagClient   — 模块级单例（lifespan 启动时构造）
    RagResult / Document            — 响应数据类

关键不变量：
  - 搜索统一调用 /api/v1/rag/search，workspace_ids 放在请求体中。
  - 5xx / TimeoutException / ConnectError → rag_retry 自愈；
    401 / 403 / 其他 4xx → 不重试。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from chat.src.config import settings
from chat.src.infra.retry import rag_retry
from chat.src.rag.schemas import Document, SearchRequest

RAG_DEFAULT_TOP_K = 5
PATH = "/api/v1/rag/search"


# ──────────────────────────── RagResult ────────────────────────────


@dataclass
class RagResult:
    """RAG 客户端返回结构。"""

    success: bool = True
    status_code: int = 200
    documents: list[Document] = field(default_factory=list)
    elapsed_ms: float = 0.0
    raw: dict = field(default_factory=dict)
    error: str = ""


# ──────────────────────────── RagClient ────────────────────────────


class RagClient:
    """转发用户 Bearer 的 RAG HTTP 客户端。

    构造参数（全部 keyword-only）：
        base_url, timeout=10.0, max_retries=DEPRECATED

    注意：重试由 infra.retry.rag_retry 装饰器承担（驱动来源 settings.rag_max_retries），
    `max_retries` 形参保留仅为向后兼容（test_client.py 旧测试仍传入），不生效。
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 2,  # noqa: ARG003  DEPRECATED: 见类 docstring
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        # httpx.AsyncClient 单例：连接池复用 + 避免 leak
        # 注意：测试用 install_mock_transport fixture 通过 monkeypatch 替换
        # httpx.AsyncClient，因此这里直接用裸 httpx.AsyncClient。
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=20,
            ),
        )

    async def aclose(self) -> None:
        """释放 httpx 连接池。重复调用安全。"""
        try:
            await self._client.aclose()
        except Exception:
            # 连接已关闭时不抛错（acquire/release 跨 task 场景常见）
            pass

    # ─────────────────────── search ───────────────────────

    @rag_retry
    async def _do_post(self, url: str, body_bytes: bytes, headers: dict) -> httpx.Response:
        """实际发出 HTTP POST。

        5xx 由 rag_retry 装饰器重试（raise_for_status 抛 HTTPStatusError），
        4xx 不重试（不抛错 → 不触发重试条件）。
        """
        resp = await self._client.post(url, content=body_bytes, headers=headers)
        if resp.status_code >= 500:
            # 让 rag_retry 看见 HTTPStatusError → 重试
            resp.raise_for_status()
        return resp

    async def search(
        self,
        req: SearchRequest,
        *,
        authorization: str | None = None,
        app_id: str | None = None,
        api_key: str | None = None,
    ) -> RagResult:
        """单次 RAG 检索。

        构造 JSON body 字节级发送 → 解 JSON → 解析 results[] 为 Document。
        """
        # 1. 构造请求体（紧凑序列化，无空格；model_dump 已 exclude_none）
        payload = req.model_dump(exclude_none=True)
        body_bytes = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }
        if authorization and authorization.lower().startswith("bearer "):
            headers["Authorization"] = authorization
        if api_key:
            headers["X-API-Key"] = api_key
        if app_id:
            headers["X-App-Id"] = app_id
        url = self._base_url + PATH

        # 2. 发出请求（瞬态故障由 rag_retry 自愈）
        try:
            resp = await self._do_post(url, body_bytes, headers)
        except httpx.HTTPStatusError as e:
            # 5xx 重试耗尽：保留真实状态码（rag_retry 已尝试 max_attempts 次）
            status_code = e.response.status_code if e.response else 500
            return RagResult(
                success=False,
                status_code=status_code,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=str(e),
            )
        except Exception as e:
            # 其他异常（连接错误、超时重试耗尽等）→ status_code=0
            return RagResult(
                success=False,
                status_code=0,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=str(e),
            )

        # 3. 状态码处理
        status = resp.status_code
        if status >= 400:
            # 401/403/422 不重试（已由 rag_retry 跳过），5xx 在 rag_retry 已重试
            body_snip = (resp.text or "")[:200]
            return RagResult(
                success=False,
                status_code=status,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=f"http {status}: {body_snip}",
            )

        # 4. 解析响应
        try:
            data = resp.json()
        except Exception as e:
            return RagResult(
                success=False,
                status_code=status,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=f"invalid json: {e}",
            )

        docs: list[Document] = []
        for raw_doc in data.get("results", []) or []:
            try:
                docs.append(Document(**raw_doc))
            except Exception:
                pass

        return RagResult(
            success=True,
            status_code=status,
            documents=docs,
            elapsed_ms=float(data.get("elapsed_ms") or 0.0),
            raw=data,
            error="",
        )

# ──────────────────────────── 单例 ────────────────────────────


_client: RagClient | None = None


def _build_client_from_settings() -> RagClient:
    """从 settings 构造 RagClient 单例。"""
    return RagClient(
        base_url=settings.rag_base_url,
        timeout=settings.rag_timeout,
    )


def get_rag_client() -> RagClient:
    """模块级单例。第一次调用时构造。"""
    global _client
    if _client is None or _client._client.is_closed:
        _client = _build_client_from_settings()
    return _client


def _reset_client_for_tests() -> None:
    """测试 fixture 用：清空单例，强制下次 get_rag_client() 重建。"""
    global _client
    _client = None
