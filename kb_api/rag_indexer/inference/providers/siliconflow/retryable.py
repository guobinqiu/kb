from __future__ import annotations

import httpx


def _retryable_response(response: httpx.Response | None) -> bool:
    return response is None or 500 <= response.status_code < 600
