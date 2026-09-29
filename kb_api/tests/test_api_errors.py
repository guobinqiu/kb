from fastapi.testclient import TestClient


def test_http_exception_uses_error_response_shape(system):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "Documents", "app_id": "documents"}, headers=system["headers"]
    ).json()["app"]
    workspace = system["client"].post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": "Documents"}, headers=system["headers"]
    ).json()["workspace"]
    system["dao"].create_file(
        id="11111111-1111-4111-8111-111111111111",
        workspace_id=workspace["id"],
        filename="report.txt",
        s3_url="s3://kb/uploads/report.txt",
        mime_type="text/plain",
        size_bytes=12,
        checksum=None,
        status="indexed",
        error=None,
        created_by=system["admin"]["id"],
        indexed_at=None,
    )

    response = system["client"].delete(f"/api/v1/workspaces/{workspace['id']}", headers=system["headers"])

    assert response.status_code == 409
    assert response.json()["error"] == "Workspace contains files"
    assert response.json()["service"] == "kb_api"
    assert response.json()["retryable"] is False
    assert "traceId" in response.json()
    assert "detail" not in response.json()


def test_unhandled_upload_error_returns_original_detail(system, monkeypatch):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "Documents", "app_id": "documents"}, headers=system["headers"]
    ).json()["app"]
    workspace = system["client"].post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": "Documents"}, headers=system["headers"]
    ).json()["workspace"]

    def fail_presign(*_args, **_kwargs):
        raise RuntimeError("bucket location connection refused")

    monkeypatch.setattr(system["storage"], "presign_put", fail_presign, raising=False)
    client = TestClient(system["client"].app, raise_server_exceptions=False)
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/files/upload-url",
        json={"filename": "report.txt"},
        headers=system["headers"],
    )

    assert response.status_code == 500
    assert response.json()["error"] == "bucket location connection refused"
    assert response.json()["service"] == "kb_api"
