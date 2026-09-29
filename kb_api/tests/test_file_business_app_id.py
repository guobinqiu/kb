from kb_api.api.services.rabbitmq import INDEX_TASK_QUEUE
from kb_api.tests.helpers import upload_file


def test_file_index_and_delete_tasks_use_business_app_id(system):
    client = system["client"]
    headers = system["headers"]
    app_response = client.post(
        "/api/v1/apps", json={"name": "Documents", "app_id": "imsdom"}, headers=headers
    )
    assert app_response.status_code == 201
    app = app_response.json()["app"]
    workspace = client.post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": "Documents"}, headers=headers,
    ).json()["workspace"]
    record = upload_file(system, workspace_id=workspace["id"], filename="a.txt")
    queue_name, task = system["queue"].messages[-1]
    assert queue_name == INDEX_TASK_QUEUE
    assert task["app_id"] == "imsdom"
    assert task["workspace_id"] == workspace["id"]
    assert app["id"] != task["app_id"]

    deleted = client.delete(f"/api/v1/workspaces/{workspace['id']}/files/{record['id']}", headers=headers)
    assert deleted.status_code == 202
    assert system["queue"].messages[-1][1]["app_id"] == "imsdom"
