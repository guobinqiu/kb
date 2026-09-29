import pytest

from kb_api.rag_retriever.inference.config_loader import DenseModelConfig, InferenceConfig
from kb_api.rag_retriever.inference.models import EmbeddingSpec, RoutedDenseClient
from kb_api.rag_retriever.inference.service import load_inference_components


class DenseClient:
    ready = True

    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.vector_size = dimensions
        self.close_count = 0

    def embed_query(self, text: str) -> list[float]:
        return [float(self.vector_size)]

    def close(self):
        self.close_count += 1
        self.ready = False


def test_routed_dense_uses_default_model_and_closes_all_clients():
    qwen = EmbeddingSpec(provider="siliconflow-cn", model="Qwen/Qwen3-Embedding-0.6B", dimensions=1024)
    bge = EmbeddingSpec(provider="tei", model="BAAI/bge-m3", dimensions=768)
    clients = {spec: DenseClient(spec.model, spec.dimensions) for spec in (qwen, bge)}
    routed = RoutedDenseClient(clients, default=qwen)

    assert (routed.model, routed.vector_size, routed.embed_query("query")) == (qwen.model, 1024, [1024.0])
    routed.close()
    assert not routed.ready
    assert [client.close_count for client in clients.values()] == [1, 1]


def test_routed_dense_rejects_unconfigured_default():
    default = EmbeddingSpec(provider="tei", model="BAAI/bge-m3", dimensions=1024)

    with pytest.raises(ValueError, match="embedding model is not configured"):
        RoutedDenseClient({}, default=default)


def test_factory_builds_all_providers_with_configured_default():
    default = EmbeddingSpec("tei", "BAAI/bge-m3", 768)
    config = InferenceConfig(
        dense_models=(
            DenseModelConfig("siliconflow-cn", "Qwen/embedding", 1024, "https://sf.example/v1", 10, "key"),
            DenseModelConfig("tei", default.model, default.dimensions, "http://tei.example", 20),
        ),
        embedding=default,
    )
    components = load_inference_components(config)
    clients = list(components.dense._clients.values())
    try:
        assert [client.model for client in clients] == ["Qwen/embedding", default.model]
        assert components.embedding == default
        assert components.dense.model == default.model
        assert components.dense.vector_size == 768
        assert components.ping()
    finally:
        components.close()
    assert not components.ping()
    assert all(not client.ready for client in clients)
