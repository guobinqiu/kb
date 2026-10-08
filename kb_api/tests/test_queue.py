import json
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

from kb_api.api.services.rabbitmq import RabbitMQClient
from kb_api.tests.helpers import upload_file


def _upload(system):
    app = system["client"].post(
        "/api/v1/apps", json={"name": "Queue Test", "app_id": "queue_test"}, headers=system["headers"]
    ).json()["app"]
    workspace = system["client"].post(
        f"/api/v1/apps/{app['id']}/workspaces", json={"name": "Queue Test"}, headers=system["headers"]
    ).json()["workspace"]
    return upload_file(system, workspace_id=workspace["id"], filename="queue.txt", data=b"data")


def test_index_result_api_applies_success(system):
    record = _upload(system)
    response = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "index", "file_id": record["id"], "status": "indexed", "indexed_at": "2026-09-22T12:00:00+00:00", "error": None},
        headers=system["service_headers"],
    )
    assert response.status_code == 204, response.text
    stored = system["dao"].get_file(record["id"])
    assert stored["status"] == "indexed"
    assert stored["error"] is None
    assert datetime.fromisoformat(stored["indexed_at"]) == datetime.fromisoformat("2026-09-22T12:00:00+00:00")


def test_index_result_api_updates_failure_and_delete_success_soft_deletes(system):
    record = _upload(system)
    error = {"error": "parse failed", "service": "parser", "retryable": False, "traceId": "a" * 32}
    response = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "index", "file_id": record["id"], "status": "failed", "error": error, "indexed_at": None},
        headers=system["service_headers"],
    )
    assert response.status_code == 204, response.text
    failed = system["dao"].get_file(record["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == error
    assert failed["indexed_at"] is None

    system["client"].delete(f"/api/v1/workspaces/{record['workspace_id']}/files/{record['id']}", headers=system["headers"])
    response = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "delete", "file_id": record["id"], "status": "deleted", "error": None, "indexed_at": None},
        headers=system["service_headers"],
    )
    assert response.status_code == 204, response.text
    deleted = system["dao"].get_file(record["id"], include_deleted=True)
    assert deleted["deleted_at"] is not None
    assert record["s3_url"] in system["storage"].deleted


def test_index_result_api_rejects_user_token(system):
    record = _upload(system)
    response = system["client"].post(
        "/api/v1/index-results",
        json={"operation": "index", "file_id": record["id"], "status": "indexed"},
        headers=system["headers"],
    )

    assert response.status_code == 401


def test_publish_declares_durable_queue_and_sends_persistent_json(monkeypatch):
    channel = Mock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.channel.return_value = channel
    broker = RabbitMQClient("amqp://unused")
    monkeypatch.setattr(broker, "_new_connection", lambda: connection)
    payload = {"file_id": "file-1", "operation": "index"}

    broker.publish("tasks", payload)

    channel.queue_declare.assert_called_once_with(queue="tasks", durable=True)
    channel.basic_publish.assert_called_once()
    sent = channel.basic_publish.call_args.kwargs
    assert sent["exchange"] == ""
    assert sent["routing_key"] == "tasks"
    assert isinstance(sent["body"], bytes)
    assert json.loads(sent["body"]) == payload
    assert sent["properties"].content_type == "application/json"
    assert sent["properties"].delivery_mode == 2
    connection.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("operation", ["queue_declare", "basic_publish"])
def test_publish_propagates_broker_failure_and_exits_connection(monkeypatch, operation):
    channel = Mock()
    error = RuntimeError("broker unavailable")
    getattr(channel, operation).side_effect = error
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.channel.return_value = channel
    broker = RabbitMQClient("amqp://unused")
    monkeypatch.setattr(broker, "_new_connection", lambda: connection)

    with pytest.raises(RuntimeError) as raised:
        broker.publish("tasks", {"file_id": "file-1"})

    assert raised.value is error
    connection.__exit__.assert_called_once()
    exit_type, exit_error, exit_traceback = connection.__exit__.call_args.args
    assert exit_type is RuntimeError
    assert exit_error is error
    assert exit_traceback is not None
    if operation == "queue_declare":
        channel.basic_publish.assert_not_called()
