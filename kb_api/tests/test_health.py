def test_health(system):
    response = system["client"].get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "kb_api"}
