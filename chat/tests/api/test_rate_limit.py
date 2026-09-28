import pytest
from starlette.requests import Request

from chat.src.api.middleware.rate_limit import _get_key


pytestmark = pytest.mark.unit


def _request(headers: list[tuple[bytes, bytes]], client: tuple[str, int] = ("10.0.0.1", 1234)) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/llm/chat/stream",
        "headers": headers,
        "client": client,
    })


def test_get_key_uses_forwarded_for_value():
    request = _request([(b"x-forwarded-for", b"1.1.1.1")])

    assert _get_key(request) == "1.1.1.1"


def test_get_key_does_not_trust_first_forwarded_for_segment():
    request = _request([(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")])

    assert _get_key(request) == "1.1.1.1, 2.2.2.2"


def test_get_key_falls_back_to_remote_address():
    request = _request([])

    assert _get_key(request) == "10.0.0.1"
