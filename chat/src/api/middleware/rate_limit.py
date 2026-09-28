from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from chat.src.config import settings


def _get_key(request: Request) -> str:
    """限流 key：优先按 X-Forwarded-For 中的原始客户端 IP。"""
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for
    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.rate_limit_storage,
)
