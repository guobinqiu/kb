from __future__ import annotations

from kb_api.rag_search.inference.config_loader import DenseModelConfig, InferenceConfig, load_inference_config
from kb_api.rag_search.inference.models import EmbeddingSpec, RoutedDenseClient
from kb_api.rag_search.inference.providers.siliconflow import SiliconFlowDenseClient, SiliconFlowRerankClient
from kb_api.rag_search.inference.providers.tei import TeiDenseClient, TeiRerankClient


class InferenceComponents:
    def __init__(self, dense, *, rerank=None, embedding: EmbeddingSpec | None = None):
        self.dense = dense
        self.rerank = rerank
        self.embedding = embedding
        self.ready = True

    def ping(self) -> bool:
        ping = getattr(self.dense, "ping", None)
        return self.ready and (bool(ping()) if callable(ping) else bool(getattr(self.dense, "ready", False)))

    def close(self) -> None:
        if self.rerank is not None:
            self.rerank.close()
        self.dense.close()
        self.ready = False

def load_inference_components(config: InferenceConfig | None = None):
    config = config or load_inference_config()
    if config.embedding is not None and config.dense_models:
        clients = {}
        for model in config.dense_models:
            if model.dimensions is None:
                continue
            spec = EmbeddingSpec(model.provider, model.model, model.dimensions)
            clients[spec] = _build_dense(model)
        return InferenceComponents(
            RoutedDenseClient(clients, default=config.embedding),
            rerank=_build_rerank(config),
            embedding=config.embedding,
        )
    if config.siliconflow is not None:
        remote = config.siliconflow
        model = DenseModelConfig(
            provider="siliconflow", model=remote.dense_model, dimensions=remote.dimensions,
            base_url=remote.base_url, timeout=remote.dense_timeout,
            api_key=remote.api_key, retry=remote.retry,
        )
    elif config.tei is not None:
        remote = config.tei
        model = DenseModelConfig(
            provider="tei", model=remote.dense_model, dimensions=remote.dimensions,
            base_url=remote.dense_url, timeout=remote.dense_timeout, retry=remote.retry,
        )
    else:
        raise RuntimeError("inference provider is not configured")
    return InferenceComponents(_build_dense(model), rerank=_build_rerank(config), embedding=config.embedding)


def _build_dense(config: DenseModelConfig):
    if config.provider == "siliconflow" or config.provider.startswith("siliconflow-"):
        return SiliconFlowDenseClient(
            config.base_url, model=config.model, timeout=config.timeout, api_key=config.api_key,
            dimensions=config.dimensions, retry=config.retry,
        )
    if config.provider == "tei":
        return TeiDenseClient(
            config.base_url, config.model, config.timeout,
            dimensions=config.dimensions, retry=config.retry,
        )
    raise ValueError(f"unsupported inference provider: {config.provider}")


def _build_rerank(config: InferenceConfig):
    if config.siliconflow is not None:
        remote = config.siliconflow
        if remote.rerank_model:
            return SiliconFlowRerankClient(
                remote.base_url, model=remote.rerank_model,
                timeout=remote.rerank_timeout if remote.rerank_timeout is not None else remote.dense_timeout,
                api_key=remote.api_key, retry=remote.retry,
            )
    if config.tei is not None and config.tei.rerank_url and config.tei.rerank_model:
        remote = config.tei
        return TeiRerankClient(
            remote.rerank_url, remote.rerank_model,
            remote.rerank_timeout if remote.rerank_timeout is not None else remote.dense_timeout,
            retry=remote.retry,
        )
    return None
