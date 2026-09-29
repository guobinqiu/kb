import json

import httpx
import pytest
import yaml
from kb_api.rag_indexer.inference.service import InferenceComponents
from kb_api.rag_indexer.inference.providers.tei import TeiDenseClient
from kb_api.rag_indexer.inference.config_loader import load_inference_config
from kb_api.rag_indexer.common.config import RetryConfig


@pytest.fixture
def make_client():

    clients = []

    def make(handler, **kwargs):
        dense_url = kwargs.pop("dense_url", "http://tei-dense:80")
        dense_model = kwargs.pop("dense_model", "BAAI/bge-m3")
        dense = TeiDenseClient(
            base_url=dense_url,
            model=dense_model,
            timeout=12.0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            **kwargs,
        )
        client = InferenceComponents(dense)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_tei_config_selects_enabled_dense(tmp_path, monkeypatch):

    monkeypatch.setenv("TEI_TIMEOUT", "1")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"inference": {
        "tei": {
            "enable": True,
            "retry": {"max_attempts": 3, "interval_seconds": 0.5},
            "dense": {
                "bge_base": {
                    "enable": False,
                    "model_name": "BAAI/bge-base-zh-v1.5",
                    "base_url": "http://tei-bge-base:80",
                },
                "bge_m3": {
                    "enable": True,
                    "model_name": "BAAI/bge-m3",
                    "base_url": "http://tei-bge-m3:80",
                    "dimensions": 1024,
                    "timeout": 90,
                    "batch_size": 16,
                },
            },
            "rerank": {
                "bge_m3": {
                    "enable": True,
                    "model_name": "BAAI/bge-reranker-v2-m3",
                    "base_url": "http://tei-rerank:80",
                    "timeout": 30,
                },
            },
        },
    }}))

    config = load_inference_config(path)

    assert config.tei is not None
    assert config.tei.dense_url == "http://tei-bge-m3:80"
    assert config.tei.dense_model == "BAAI/bge-m3"
    assert config.tei.dimensions == 1024
    assert config.tei.dense_timeout == 90.0
    assert config.tei.retry.max_attempts == 3
    assert config.tei.retry.interval_seconds == 0.5
    assert config.tei.batch_size == 16
    assert config.dense_models[0].batch_size == 16


def test_dense_uses_tei_embed_endpoint(make_client):
    def handler(request):
        assert str(request.url) == "http://tei-dense/v1/embeddings"
        assert request.extensions["timeout"]["read"] == 12.0
        payload = json.loads(request.content)
        assert payload == {"input": ["a", "b"], "model": "BAAI/bge-m3", "encoding_format": "float"}
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
            ],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2)

    assert client.dense.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert client.dense.vector_size == 2


def test_retryable_dense_failure_is_retried(make_client, monkeypatch):

    monkeypatch.setattr("kb_api.rag_indexer.common.retry.time.sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2, retry=RetryConfig(max_attempts=3, interval_seconds=0.5))

    assert client.dense.embed_documents(["a"]) == [[0.1, 0.2]]
    assert len(calls) == 2


def test_dense_query_uses_single_input_string(make_client):
    def handler(request):
        assert str(request.url) == "http://tei-dense/v1/embeddings"
        assert json.loads(request.content) == {"input": "q", "model": "BAAI/bge-m3", "encoding_format": "float"}
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.5, 0.6]},
            ],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2)

    assert client.dense.embed_query("q") == [0.5, 0.6]


@pytest.mark.parametrize("batch_size, expected_sizes", [(32, [32, 32, 32, 17]), (16, [16, 16, 16, 16, 16, 16, 16, 1])])
def test_dense_batches_documents_and_preserves_order(make_client, batch_size, expected_sizes):
    batches = []

    def handler(request):
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        if len(texts) > 32:
            return httpx.Response(413, json={"error": "batch size exceeds 32"})
        return httpx.Response(200, json={
            "data": [
                {"index": index, "embedding": [float(text), 0.0]}
                for index, text in reversed(list(enumerate(texts)))
            ],
        })

    client = make_client(handler, dimensions=2, batch_size=batch_size)

    assert client.dense.embed_documents([str(index) for index in range(113)]) == [
        [float(index), 0.0] for index in range(113)
    ]
    assert [len(batch) for batch in batches] == expected_sizes
