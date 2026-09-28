from pathlib import Path

NGINX_CONFIG = Path(__file__).resolve().parents[2] / "deploy/nginx/nginx.conf"


def test_gateway_uses_org_routes_and_trusted_identity_header():
    config = NGINX_CONFIG.read_text()

    assert "/api/v1/(apps|orgs|users|files)" in config
    assert "/api/v1/(apps|nodes|users|files)" not in config
    assert config.count("auth_request_set $org_id $upstream_http_x_org_id;") == 3
    assert config.count("proxy_set_header X-Org-Id $org_id;") == 3
    assert "X-Node-Id" not in config
    assert "$node_id" not in config
