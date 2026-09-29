import httpx
import pytest

from kb_api.rag_indexer.common.upstream import retryable_response


@pytest.mark.parametrize("status,body,expected", [
    (503, {"code": 50505}, True),
    (503, {"code": "50505"}, True),
    (500, {"code": 50505}, True),
    (429, {"message": "please retry"}, False),
    (402, {"code": 30001}, False),
    (503, {"code": 99999}, True),
    (503, [], True),
])
def test_retryable_uses_http_status(status, body, expected):
    assert retryable_response(httpx.Response(status, json=body)) is expected


def test_html_and_missing_response_are_retryable_when_status_is_temporary():
    assert retryable_response(httpx.Response(503, text="bad gateway")) is True
    assert retryable_response(None) is True
