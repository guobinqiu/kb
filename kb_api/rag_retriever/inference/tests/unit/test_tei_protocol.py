import json

import httpx
import pytest
import yaml

from kb_api.rag_retriever.common.config import RetryConfig
from kb_api.rag_retriever.inference.config_loader import InferenceConfig, TeiConfig, load_inference_config
from kb_api.rag_retriever.inference.service import load_inference_components


@pytest.fixture
def make_client(monkeypatch):
    clients = []
    http_client = httpx.Client

    def make(handler, **kwargs):
        dense_url = kwargs.pop("dense_url", "http://tei-dense:80")
        dense_model = kwargs.pop("dense_model", "BAAI/bge-m3")
        rerank_url = kwargs.pop("rerank_url", "http://tei-rerank:80")
        rerank_model = kwargs.pop("rerank_model", "BAAI/bge-reranker-v2-m3")
        config = TeiConfig(
            dense_url=dense_url,
            dense_model=dense_model,
            rerank_url=rerank_url,
            rerank_model=rerank_model,
            dense_timeout=12.0,
            rerank_timeout=7.0,
            **kwargs,
        )
        with monkeypatch.context() as patch:
            patch.setattr(httpx, "Client", lambda **options: http_client(
                **options, transport=httpx.MockTransport(handler),
            ))
            client = load_inference_components(InferenceConfig(tei=config))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_tei_config_selects_enabled_dense_and_optional_rerank(tmp_path, monkeypatch):
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
    assert config.tei.rerank_url == "http://tei-rerank:80"
    assert config.tei.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert config.tei.dense_timeout == 90.0
    assert config.tei.rerank_timeout == 30.0
    assert config.tei.retry.max_attempts == 3
    assert config.tei.retry.interval_seconds == 0.5


def test_dense_uses_tei_embed_endpoint_and_dimension(make_client):
    def handler(request):
        assert str(request.url) == "http://tei-dense/v1/embeddings"
        assert request.extensions["timeout"]["read"] == 12.0
        payload = json.loads(request.content)
        assert payload == {"input": "a", "model": "BAAI/bge-m3", "encoding_format": "float"}
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
            ],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2)

    assert client.dense.embed_query("a") == [0.1, 0.2]
    assert client.dense.vector_size == 2


def test_retryable_dense_failure_is_retried(make_client, monkeypatch):
    monkeypatch.setattr("kb_api.rag_retriever.common.retry.time.sleep", lambda seconds: None)
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

    assert client.dense.embed_query("a") == [0.1, 0.2]
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


def test_rerank_uses_tei_rerank_endpoint(make_client):
    items = [{"content": "a", "id": "a"}, {"content": "b", "metadata": {"page": 2}}]

    def handler(request):
        assert str(request.url) == "http://tei-rerank/rerank"
        assert json.loads(request.content) == {
            "query": "q",
            "texts": ["a", "b"],
            "raw_scores": False,
            "return_text": False,
        }
        return httpx.Response(200, json=[
            {"index": 1, "score": 0.9},
        ])

    client = make_client(handler)

    assert client.rerank.rerank("q", items, 1) == [
        {"content": "b", "metadata": {"page": 2}, "_score": 0.9},
    ]
    assert "_score" not in items[1]


def test_rerank_accepts_full_sorted_rows_and_applies_top_k(make_client):
    items = [{"content": "a"}, {"content": "b"}]

    def handler(request):
        return httpx.Response(200, json=[
            {"index": 0, "score": 0.99},
            {"index": 1, "score": 0.01},
        ])

    client = make_client(handler)

    assert client.rerank.rerank("q", items, 1) == [
        {"content": "a", "_score": 0.99},
    ]


def test_rerank_can_be_disabled(make_client):
    client = make_client(lambda request: httpx.Response(500), rerank_model=None, rerank_url=None)

    assert client.rerank is None
    assert client.ping()
