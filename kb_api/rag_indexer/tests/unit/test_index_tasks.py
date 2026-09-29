from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from kb_api.rag_indexer.index_tasks import IndexTask, IndexTaskConsumer, process_index_task, task_result
from kb_api.rag_indexer.core.scope import collection_name_for_app
from kb_api.rag_indexer.core.index.errors import index_stage


class FakeVector:
    def __init__(self):
        self.deleted_file_ids = []

    @contextmanager
    def app_scope(self, app_id):
        yield

    def delete_file_chunks(self, file_id):
        self.deleted_file_ids.append(file_id)
        return 3


def test_process_index_task_indexes_file_in_app_scope_with_workspace_metadata(monkeypatch):
    vector = FakeVector()
    state = SimpleNamespace(vector_client=vector)
    calls = []
    monkeypatch.setattr(
        "kb_api.rag_indexer.index_tasks._presigned_url",
        lambda state, s3_url: "http://minio/file.pdf",
    )
    monkeypatch.setattr(
        "kb_api.rag_indexer.index_tasks.index_presigned_file",
        lambda state, **kwargs: calls.append(kwargs) or (2, 120),
    )

    result = process_index_task(
        state,
        IndexTask(
            operation="index",
            app_id="imsdom",
            workspace_id="2f59393d-41b8-4cab-8bbd-2aee2e7c7234",
            file_id="file-1",
            s3_url="s3://rag/file.pdf",
            filename="file.pdf",
        ),
    )

    assert calls == [{
        "file_id": "file-1",
        "presigned_url": "http://minio/file.pdf",
        "s3_url": "s3://rag/file.pdf",
        "filename": "file.pdf",
        "extra_metadata": {"workspace_id": "2f59393d-41b8-4cab-8bbd-2aee2e7c7234"},
    }]
    assert result == {
        "operation": "index",
        "file_id": "file-1",
        "success": True,
        "status": "indexed",
        "error": None,
        "retryable": False,
        "indexed_at": result["indexed_at"],
        "chunk_count": 2,
        "file_size": 120,
    }
    assert result["indexed_at"].endswith("+00:00")


def test_process_delete_task_deletes_file_in_app_scope():
    vector = FakeVector()
    state = SimpleNamespace(vector_client=vector)

    result = process_index_task(
        state,
        IndexTask(
            operation="delete",
            app_id="imsdom",
            workspace_id="workspace-1",
            file_id="file-1",
        ),
    )

    assert vector.deleted_file_ids == ["file-1"]
    assert result == {
        "operation": "delete",
        "file_id": "file-1",
        "success": True,
        "status": "deleted",
        "error": None,
        "retryable": False,
        "indexed_at": None,
        "deleted_chunks": 3,
    }


def test_index_task_requires_storage_fields():
    with pytest.raises(ValueError, match="s3_url and filename are required"):
        IndexTask(
            operation="index",
            app_id="imsdom",
            workspace_id="workspace-1",
            file_id="file-1",
        )


def test_task_result_preserves_retryable_error(monkeypatch):

    error = UpstreamServiceError(
        service="parser",
        error="temporarily unavailable",
        retryable=True,
        status_code=503,
        trace_id="a" * 32,
    )
    def fail(state, task):
        with index_stage("embedding", "inference"):
            raise error

    monkeypatch.setattr("kb_api.rag_indexer.index_tasks.process_index_task", fail)

    result = task_result(object(), {
        "operation": "delete",
        "app_id": "imsdom",
        "workspace_id": "workspace-1",
        "file_id": "file-1",
    })

    assert result == {
        "operation": "delete",
        "file_id": "file-1",
        "success": False,
        "status": "delete_failed",
        "error": {
            "error": "temporarily unavailable",
            "service": "parser",
            "retryable": True,
            "traceId": "a" * 32,
        },
        "retryable": True,
        "indexed_at": None,
    }


def test_consumer_posts_one_result_for_each_task(monkeypatch):
    posted = []
    callback = SimpleNamespace(post=lambda value: posted.append(value))
    monkeypatch.setattr(
        "kb_api.rag_indexer.index_tasks.task_result",
        lambda state, value: {"file_id": value["file_id"], "success": True},
    )

    IndexTaskConsumer(object(), callback).handle({"file_id": "file-1"})

    assert posted == [{"file_id": "file-1", "success": True}]


def test_consumer_raises_when_result_callback_fails(monkeypatch):
    def fail(_value):
        raise RuntimeError("callback unavailable")

    callback = SimpleNamespace(post=fail)
    monkeypatch.setattr(
        "kb_api.rag_indexer.index_tasks.task_result",
        lambda state, value: {"file_id": value["file_id"], "success": False},
    )

    with pytest.raises(RuntimeError, match="callback unavailable"):
        IndexTaskConsumer(object(), callback).handle({"file_id": "file-1"})


def test_business_app_id_maps_to_vector_collection_name():
    assert collection_name_for_app("imsdom") == "imsdom_chunks"


def test_task_requires_workspace_identity():
    with pytest.raises(ValueError, match="workspace_id is required"):
        IndexTask.from_dict({"operation": "delete", "app_id": "imsdom", "file_id": "file-1"})
    with pytest.raises(ValueError, match="app_id is required"):
        IndexTask.from_dict({"operation": "delete", "workspace_id": "workspace-1", "file_id": "file-1"})


def test_task_message_uses_app_and_workspace_without_workspace_key():
    task = IndexTask.from_dict({
        "operation": "delete",
        "app_id": "imsdom",
        "workspace_id": "workspace-1",
        "file_id": "file-1",
    })

    assert task.app_id == "imsdom"
    assert task.workspace_id == "workspace-1"
    assert not hasattr(task, "workspace_key")
    assert not hasattr(task, "node_id")


def test_task_message_rejects_legacy_workspace_key():
    with pytest.raises(ValueError, match="workspace_key is not supported"):
        IndexTask.from_dict({
            "operation": "delete",
            "app_id": "imsdom",
            "workspace_id": "workspace-1",
            "workspace_key": "legacy_workspace",
            "file_id": "file-1",
        })
