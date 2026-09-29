"""统一重试策略。

网络级重试（瞬态故障自愈）由 RetryPolicy + build_retry() 管理。
业务级重试（用户修正后重走流程）由 graph state 计数器管理，上限在 CallConfig 中配置。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# ── 重试策略 ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RetryPolicy:
    """网络级重试策略参数。"""
    max_attempts: int = 3
    min_wait: float = 1.0
    max_wait: float = 8.0
    multiplier: float = 1.0


# 预定义策略
LLM_RETRY = RetryPolicy(max_attempts=3, min_wait=0.5, max_wait=1)
API_RETRY = RetryPolicy(max_attempts=5, min_wait=0.5, max_wait=1)
RAG_RETRY = RetryPolicy(max_attempts=3, min_wait=0.3, max_wait=2.0)


# ── 运行时 rag_retry ──────────────────────────────────────────
# rag_retry 默认走 RAG_RETRY（max_attempts=3），但 settings.rag_max_retries 可在
# 应用启动后覆盖（架构 §4.6）。Decorator 必须 import 即生效（rag/client.py 用法），
# 同时允许 settings 后续修改 —— 解决方案：proxy 类首次 __call__ 时读取 settings
# 缓存，后续不再重读。测试用 _reset_rag_retry_for_tests() 强制重建（settings 已
# 改 + 期望下次调用拿新 policy 的场景）。

def _resolve_rag_policy() -> RetryPolicy:
    """Build RAG retry policy honoring settings.rag_max_retries at runtime.

    语义：settings.rag_max_retries = N 表示最多重试 N 次（不含初次）。
    对应 tenacity stop_after_attempt = N + 1（初次 + N 次重试）。
    settings 缺失或 rag_max_retries < 0 时回退 RAG_RETRY 默认值（max_attempts=3）。
    """
    try:
        from chat.src.config import settings
        n = int(getattr(settings, "rag_max_retries", RAG_RETRY.max_attempts - 1))
    except Exception:
        n = RAG_RETRY.max_attempts - 1
    if n < 0:
        n = 0
    return RetryPolicy(
        max_attempts=n + 1,
        min_wait=RAG_RETRY.min_wait,
        max_wait=RAG_RETRY.max_wait,
        multiplier=RAG_RETRY.multiplier,
    )


_rag_retry_cache: RetryPolicy | None = None
_rag_retry_decorator: Callable[..., Any] | None = None


def _get_rag_retry() -> Callable[..., Any]:
    """Lazy build + cache: 首次 @rag_retry 装饰时读 settings；测试调用
    _reset_rag_retry_for_tests() 强制重建。
    """
    global _rag_retry_cache, _rag_retry_decorator
    policy = _resolve_rag_policy()
    if _rag_retry_decorator is None or policy != _rag_retry_cache:
        _rag_retry_cache = policy
        _rag_retry_decorator = build_retry(policy, _is_rag_retryable)
    return _rag_retry_decorator


def _reset_rag_retry_for_tests() -> None:
    """测试 fixture 用：清缓存，强制下次装饰时按 settings 重建。"""
    global _rag_retry_cache, _rag_retry_decorator
    _rag_retry_cache = None
    _rag_retry_decorator = None


# ── 可重试异常判定 ──────────────────────────────────────────────

def is_llm_retryable(exc: Exception) -> bool:
    """LLM 调用的可重试异常：限流、5xx、连接错误。"""
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    if isinstance(exc, APIConnectionError):
        return True
    return False


def _is_api_retryable(exc: Exception) -> bool:
    """业务 API 调用的可重试异常：超时、连接错误。"""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


def _is_rag_retryable(exc: Exception) -> bool:
    """RAG 客户端的可重试异常：超时、连接错误、5xx。401/403/其他 4xx 不重试。

    认证失败（401/403）和 4xx 业务校验失败重试无意义。
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


# ── tenacity 回调 ─────────────────────────────────────────────

def _retry_exhausted(retry_state: RetryCallState) -> None:
    """重试耗尽后 re-raise 原始异常。"""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    raise exc


# ── 构建 tenacity 装饰器 ────────────────────────────────────────

def build_retry(policy: RetryPolicy, retryable_checker):
    """根据策略和异常判定函数构建 tenacity retry 装饰器。"""
    return retry(
        retry=retry_if_exception(retryable_checker),
        stop=stop_after_attempt(policy.max_attempts),
        wait=wait_exponential(
            multiplier=policy.multiplier,
            min=policy.min_wait,
            max=policy.max_wait,
        ),
        retry_error_callback=_retry_exhausted,
    )


# 预构建装饰器
llm_retry = build_retry(LLM_RETRY, is_llm_retryable)
api_retry = build_retry(API_RETRY, _is_api_retryable)


class _RagRetryProxy:
    """Decorator proxy: @rag_retry 用法保持不变（from infra.retry import rag_retry；
    @rag_retry 装饰 target 函数），同时让 settings.rag_max_retries 在运行时生效。

    用法与 tenacity 装饰器等价：
        @rag_retry
        async def foo(...): ...

    行为：每次装饰时调 _get_rag_retry() 读 settings，构建/复用 tenacity decorator。
    测试注入 settings 改动后调 _reset_rag_retry_for_tests() 重建。
    """
    __slots__ = ()

    def __call__(self, fn):
        return _get_rag_retry()(fn)


rag_retry = _RagRetryProxy()
