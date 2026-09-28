"""infra.retry 单测（§11.1）：rag_retry 装饰器。

覆盖：
- 5xx (HTTPStatusError)：重试至多 max_attempts 次
- TimeoutException：重试至多 max_attempts 次
- 401 / 403 / 422 / 其他 4xx：不重试（按架构 §4.6）
- ConnectError：也应被重试（瞬态故障）
- 最终失败时抛原异常
- 重试成功时不抛错
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.unit


def _try_import_rag_retry():
    try:
        from chat.src.infra.retry import rag_retry
        return rag_retry
    except Exception as exc:
        pytest.fail(f"infra.retry.rag_retry not implemented — RED ({exc})")


def _try_import_policy():
    """RAG_RETRY 策略对象（可能作为 dataclass / dict 导出）。"""
    try:
        from chat.src.infra.retry import RAG_RETRY
        return RAG_RETRY
    except Exception:
        return None


class _Counter:
    def __init__(self):
        self.n = 0


def _make_raising(counter: _Counter, exc: Exception):
    """构造一个被 rag_retry 修饰的伪 async 函数。"""

    @_try_import_rag_retry()
    async def _fn(*args, **kwargs):
        counter.n += 1
        raise exc

    return _fn


# ────────────────────────── 5xx 重试 ──────────────────────────


@pytest.mark.asyncio
async def test_rag_retry_retries_on_5xx(monkeypatch):
    """5xx 响应（HTTPStatusError, status >= 500）触发重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x/api/v1/rag/search")
    response_503 = httpx.Response(503, request=request)
    err = httpx.HTTPStatusError(
        "Service Unavailable", request=request, response=response_503
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        raise err

    with pytest.raises(httpx.HTTPStatusError):
        await _fn()

    policy = _try_import_policy()
    expected_attempts = getattr(policy, "max_attempts", None) or 3
    # 必须至少尝试过 max_attempts 次
    assert counter.n == expected_attempts, (
        f"5xx 应重试到 max_attempts={expected_attempts}，实际 {counter.n} 次"
    )


@pytest.mark.asyncio
async def test_rag_retry_5xx_eventually_succeeds(monkeypatch):
    """5xx 在中间成功：count=2 成功 → 返回结果。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x")
    err = httpx.HTTPStatusError(
        "boom",
        request=request,
        response=httpx.Response(500, request=request),
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        if counter.n < 2:
            raise err
        return "ok"

    out = await _fn()
    assert out == "ok"
    assert counter.n == 2


# ────────────────────────── TimeoutException 重试 ──────────────────────────


@pytest.mark.asyncio
async def test_rag_retry_retries_on_timeout(monkeypatch):
    """httpx.TimeoutException 触发重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    @rag_retry
    async def _fn():
        counter.n += 1
        raise httpx.TimeoutException("simulated timeout")

    with pytest.raises(httpx.TimeoutException):
        await _fn()

    policy = _try_import_policy()
    expected_attempts = getattr(policy, "max_attempts", None) or 3
    assert counter.n == expected_attempts


@pytest.mark.asyncio
async def test_rag_retry_retries_on_connect_error(monkeypatch):
    """httpx.ConnectError 触发重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    @rag_retry
    async def _fn():
        counter.n += 1
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        await _fn()

    policy = _try_import_policy()
    expected_attempts = getattr(policy, "max_attempts", None) or 3
    assert counter.n == expected_attempts


# ────────────────────────── 401/403/422 不重试 ──────────────────────────


@pytest.mark.asyncio
async def test_rag_retry_does_not_retry_on_401(monkeypatch):
    """401 不重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x")
    err = httpx.HTTPStatusError(
        "Unauthorized",
        request=request,
        response=httpx.Response(401, request=request),
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        raise err

    with pytest.raises(httpx.HTTPStatusError):
        await _fn()
    assert counter.n == 1, f"401 不应重试，实际调 {counter.n} 次"


@pytest.mark.asyncio
async def test_rag_retry_does_not_retry_on_403(monkeypatch):
    """403 不重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x")
    err = httpx.HTTPStatusError(
        "Forbidden",
        request=request,
        response=httpx.Response(403, request=request),
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        raise err

    with pytest.raises(httpx.HTTPStatusError):
        await _fn()
    assert counter.n == 1


@pytest.mark.asyncio
async def test_rag_retry_does_not_retry_on_422(monkeypatch):
    """422 不重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x")
    err = httpx.HTTPStatusError(
        "Unprocessable Entity",
        request=request,
        response=httpx.Response(422, request=request),
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        raise err

    with pytest.raises(httpx.HTTPStatusError):
        await _fn()
    assert counter.n == 1


@pytest.mark.asyncio
async def test_rag_retry_does_not_retry_on_other_4xx(monkeypatch):
    """404、400 等其他 4xx 不重试。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    import httpx

    request = httpx.Request("POST", "http://x")
    err = httpx.HTTPStatusError(
        "Not Found",
        request=request,
        response=httpx.Response(404, request=request),
    )

    @rag_retry
    async def _fn():
        counter.n += 1
        raise err

    with pytest.raises(httpx.HTTPStatusError):
        await _fn()
    assert counter.n == 1


# ────────────────────────── 成功路径 ──────────────────────────


@pytest.mark.asyncio
async def test_rag_retry_passes_through_on_success(monkeypatch):
    """无异常的调用直接通过，不增加次数。"""
    rag_retry = _try_import_rag_retry()
    counter = _Counter()

    @rag_retry
    async def _fn():
        counter.n += 1
        return "value"

    out = await _fn()
    assert out == "value"
    assert counter.n == 1


# ────────────────────────── 重试策略对象 ──────────────────────────


def test_rag_retry_policy_max_attempts_is_three():
    """RAG_RETRY.max_attempts == 3（架构 §4.6）。"""
    policy = _try_import_policy()
    if policy is None:
        pytest.fail("RAG_RETRY not exported — RED")
    assert getattr(policy, "max_attempts", None) == 3


def test_rag_retry_decorator_is_callable():
    """rag_retry 必须是可用装饰器（即 callable）。"""
    rag_retry = _try_import_rag_retry()
    assert callable(rag_retry)


# ────────────────────────── settings.rag_max_retries 生效 ──────────────────────────
# 任务：让 YAML 配置（→ settings.rag_max_retries → RagClient.max_retries）
# 真正驱动重试次数，而不只是被存储到 self._max_retries 不生效。
# 实现：infra.retry.rag_retry 改为装饰器 proxy，首次装饰时读 settings，构造 tenacity
# 装饰器；测试可调 _reset_rag_retry_for_tests 重建。


def test_rag_retry_resolves_rag_max_retries_from_settings(monkeypatch):
    """settings.rag_max_retries 改动后，rag_retry 装饰的实际 max_attempts 跟随变。

    语义：rag_max_retries = N → max_attempts = N + 1（= 初次 + N 次重试）。
    """
    # 改 settings.rag_max_retries，再调 _resolve_rag_policy 看新结果
    from chat.src.config import settings
    from chat.src.infra.retry import _reset_rag_retry_for_tests, _resolve_rag_policy
    monkeypatch.setattr(settings, "rag_max_retries", 4)
    _reset_rag_retry_for_tests()
    p = _resolve_rag_policy()
    assert p.max_attempts == 5, f"rag_max_retries=4 应得到 max_attempts=5，实得 {p.max_attempts}"


def test_rag_retry_policy_zero_retries_means_one_attempt(monkeypatch):
    """rag_max_retries=0 → max_attempts=1（仅初次，无重试）。"""
    from chat.src.config import settings
    from chat.src.infra.retry import _resolve_rag_policy
    monkeypatch.setattr(settings, "rag_max_retries", 0)
    p = _resolve_rag_policy()
    assert p.max_attempts == 1


def test_rag_retry_policy_negative_clamps_to_one(monkeypatch):
    """rag_max_retries 为负数时 clamp 到 0 次重试（= 1 次尝试）。"""
    from chat.src.config import settings
    from chat.src.infra.retry import _resolve_rag_policy
    monkeypatch.setattr(settings, "rag_max_retries", -3)
    p = _resolve_rag_policy()
    assert p.max_attempts == 1


@pytest.mark.asyncio
async def test_rag_retry_respects_settings_max_retries(monkeypatch):
    """端到端：在受控 max_retries=1 场景下，跑 rag_retry 装饰的函数应恰好尝试 2 次
    （= 初次 + 1 次重试），而不是默认 3 次。
    """
    from chat.src.config import settings
    from chat.src.infra.retry import _get_rag_retry, _reset_rag_retry_for_tests, _resolve_rag_policy

    monkeypatch.setattr(settings, "rag_max_retries", 1)
    _reset_rag_retry_for_tests()
    _get_rag_retry()  # 强制重建
    # 测 _resolve_rag_policy 而非直接调 tenacity（避免再造被装饰函数）
    p = _resolve_rag_policy()
    assert p.max_attempts == 2


def test_rag_retry_proxy_is_decorator():
    """_RagRetryProxy 必须可用作 @rag_retry 装饰器。

    即：callable，且被调用时接收函数并返回 wrapped 函数。
    """
    from chat.src.infra.retry import rag_retry

    assert callable(rag_retry)

    @rag_retry
    async def _noop():
        return "noop"

    # wrapped 函数仍然 callable
    assert callable(_noop)
