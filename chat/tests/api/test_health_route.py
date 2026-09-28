import pytest

from chat.src.api.routes.health import health, router


pytestmark = pytest.mark.unit


async def test_health_route_stays_on_root_path():
    assert await health() == {"status": "ok"}
    assert any(route.path == "/health" and "GET" in route.methods and route.endpoint is health for route in router.routes)
