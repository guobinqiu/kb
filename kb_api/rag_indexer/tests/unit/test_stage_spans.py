from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from kb_api.rag_indexer.common.upstream import UpstreamServiceError
from kb_api.rag_indexer.core.index import errors, service
from kb_api.rag_indexer.core.scope import app_collection
from kb_api.rag_indexer.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient


@pytest.mark.parametrize("kind", ["upstream", "request", "runtime"])
def test_index_stage_preserves_error_semantics(kind, caplog):
    message = "https://private/password=secret"
    error = {
        "upstream": UpstreamServiceError(service="parser", error=message, retryable=True, status_code=503),
        "request": httpx.ConnectError(message),
        "runtime": RuntimeError(message),
    }[kind]
    with caplog.at_level("INFO", logger="rag_indexer"):
        with pytest.raises(UpstreamServiceError) as raised:
            with errors.index_stage("parse", "parser"):
                raise error
    if kind == "upstream":
        assert raised.value is error
    else:
        assert raised.value.__cause__ is error
        assert raised.value.retryable is (kind == "request")
    record = next(row for row in caplog.records if getattr(row, "event", None) == "index_stage")
    assert record.stage == "parse"
    assert record.status == "failed"
    assert record.elapsed_ms >= 0
    assert len(record.trace_id) == 32


def test_index_file_retains_stage_timing(caplog):
    state = SimpleNamespace(
        parser_client=SimpleNamespace(parse_file=Mock(return_value={"blocks": [{"type": "text", "kind": "paragraph", "text": "private document"}], "file_size": 16})),
        vector_client=SimpleNamespace(add_file_chunks=Mock(return_value=1)),
    )
    with caplog.at_level("INFO", logger="rag_indexer"), app_collection("app"):
        assert service.index_file(state, "file", "https://private?password=secret", "a.txt", {"workspace_id": "workspace"}) == (1, 16)
    records = [row for row in caplog.records if getattr(row, "event", None) == "index_stage"]
    assert [row.stage for row in records] == ["parse", "chunk", "vector_write"]
    assert all(row.status == "success" and row.elapsed_ms >= 0 for row in records)


def test_parse_error_precedes_missing_collection_scope():
    error = UpstreamServiceError(service="parser", error="invalid file", retryable=False, status_code=422)
    state = SimpleNamespace(parser_client=SimpleNamespace(parse_file=Mock(side_effect=error)))
    with pytest.raises(UpstreamServiceError) as raised:
        service.index_file(state, "file", "https://private", "a.txt")
    assert raised.value is error


def test_missing_blocks_still_fails_in_chunk_stage(caplog):
    state = SimpleNamespace(parser_client=SimpleNamespace(parse_file=Mock(return_value={})))
    with caplog.at_level("INFO", logger="rag_indexer"), app_collection("app"), pytest.raises(UpstreamServiceError) as raised:
        service.index_file(state, "file", "https://private", "a.txt")
    assert raised.value.service == "index"
    records = [row for row in caplog.records if getattr(row, "event", None) == "index_stage"]
    assert [(row.stage, row.status) for row in records] == [("parse", "success"), ("chunk", "failed")]


@pytest.mark.parametrize("backend", ["milvus", "qdrant"])
def test_embedding_and_database_writes_return_chunk_count(backend):
    dense = SimpleNamespace(model="dense-model", embed_documents=Mock(return_value=[[0.1, 0.2]]))
    cls = MilvusVectorClient if backend == "milvus" else QdrantVectorClient
    vector = cls(dense=dense)
    vector.client = Mock()
    vector.client.has_collection.return_value = False
    vector.client.query.return_value = []
    vector.client.count.return_value = SimpleNamespace(count=0)
    chunks = [{"id": "chunk", "content": "private document", "metadata": {"filename": "a.txt", "chunk_index": 0}}]
    with app_collection("app"):
        assert vector.add_file_chunks(chunks, "file") == 1
