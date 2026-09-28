"""Interactive API documentation exposure tests."""

from __future__ import annotations

import pytest
from starlette.routing import Match

from chat.src.main import app


pytestmark = pytest.mark.unit


def test_interactive_api_documentation_endpoints_are_not_exposed():
    assert app.docs_url is None
    assert app.openapi_url is None
    assert app.redoc_url is None

    for path in ("/docs", "/openapi.json", "/redoc"):
        scope = {"type": "http", "method": "GET", "path": path, "root_path": "", "headers": []}
        assert all(route.matches(scope)[0] is Match.NONE for route in app.routes), f"{path} should not be exposed"
