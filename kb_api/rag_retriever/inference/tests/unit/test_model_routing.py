from concurrent.futures import ThreadPoolExecutor

import pytest

from kb_api.rag_retriever.inference.models import EmbeddingSpec, RoutedDenseClient


class DenseClient:
    ready = True

    def __init__(self, model: str, dimensions: int):
        self.model = model
        self.vector_size = dimensions

    def embed_query(self, text: str) -> list[float]:
        return [float(self.vector_size)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(self.vector_size)] for _ in texts]


def test_routed_dense_uses_requested_model_without_cross_request_leakage():
    qwen = EmbeddingSpec(provider="siliconflow-cn", model="Qwen/Qwen3-Embedding-0.6B", dimensions=1024)
    bge = EmbeddingSpec(provider="tei", model="BAAI/bge-m3", dimensions=768)
    routed = RoutedDenseClient({
        qwen: DenseClient(qwen.model, qwen.dimensions),
        bge: DenseClient(bge.model, bge.dimensions),
    }, default=qwen)

    def encode(spec: EmbeddingSpec):
        with routed.use(spec):
            return routed.model, routed.vector_size, routed.embed_query("query")

    with ThreadPoolExecutor(max_workers=2) as executor:
        qwen_result, bge_result = executor.map(encode, (qwen, bge))

    assert qwen_result == (qwen.model, 1024, [1024.0])
    assert bge_result == (bge.model, 768, [768.0])
    assert routed.model == qwen.model


def test_routed_dense_rejects_unconfigured_embedding():
    default = EmbeddingSpec(provider="tei", model="BAAI/bge-m3", dimensions=1024)
    routed = RoutedDenseClient({default: DenseClient(default.model, 1024)}, default=default)

    with pytest.raises(ValueError, match="embedding model is not configured"):
        with routed.use(EmbeddingSpec(provider="tei", model="other", dimensions=1024)):
            pass

