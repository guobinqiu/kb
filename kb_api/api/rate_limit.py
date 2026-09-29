from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


_WINDOW_SECONDS = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600}
_lock = threading.Lock()
_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _check(request: Request, limit: str, scope: str) -> None:
    count, window = limit.split("/", 1)
    max_count = int(count)
    window_seconds = _WINDOW_SECONDS[window.strip().lower()]
    now = time.monotonic()
    client = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    client = client or (request.client.host if request.client else "unknown")
    with _lock:
        bucket = _requests[(scope, client)]
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if len(bucket) >= max_count:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        bucket.append(now)


def require_rate_limit(request: Request) -> None:
    _check(request, request.app.state.api_limits.rate_limit, "open")


def require_index_rate_limit(request: Request) -> None:
    _check(request, request.app.state.api_limits.rate_limit_index, "index")
