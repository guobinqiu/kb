from __future__ import annotations

from contextlib import nullcontext

from kb_api.rag_indexer.inference.config_loader import DenseModelConfig, InferenceConfig, load_inference_config
from kb_api.rag_indexer.inference.models import EmbeddingSpec, RoutedDenseClient


class InferenceComponents:
    def __init__(self, dense, *, rerank=None, embedding: EmbeddingSpec | None = None):
        self.dense = dense
        self.sparse = None
        self.rerank = rerank
        self.embedding = embedding
        self.ready = True

    def embedding_scope(self, spec: EmbeddingSpec):
        use = getattr(self.dense, "use", None)
        return use(spec) if callable(use) else nullcontext()

    def ping(self) -> bool:
        ping = getattr(self.dense, "ping", None)
        return self.ready and (bool(ping()) if callable(ping) else bool(getattr(self.dense, "ready", False)))

    def close(self) -> None:
        if self.rerank is not None:
            self.rerank.close()
        self.dense.close()
        self.ready = False

    def stop(self) -> None:
        self.close()


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
    return _load_legacy_components(config)


def _build_dense(config: DenseModelConfig):
    if config.provider.startswith("siliconflow-"):
        from kb_api.rag_indexer.inference.providers.siliconflow import SiliconFlowDenseClient

        return SiliconFlowDenseClient(
            config.base_url, model=config.model, timeout=config.timeout, api_key=config.api_key,
            dimensions=config.dimensions, retry=config.retry,
        )
    if config.provider == "tei":
        from kb_api.rag_indexer.inference.providers.tei import TeiDenseClient

        return TeiDenseClient(
            config.base_url, config.model, config.timeout,
            dimensions=config.dimensions, retry=config.retry,
        )
    raise ValueError(f"unsupported inference provider: {config.provider}")


def _build_rerank(config: InferenceConfig):
    if config.siliconflow is not None:
        from kb_api.rag_indexer.inference.providers.siliconflow import SiliconFlowRerankClient

        remote = config.siliconflow
        if remote.rerank_model:
            return SiliconFlowRerankClient(
                remote.base_url, model=remote.rerank_model,
                timeout=remote.rerank_timeout if remote.rerank_timeout is not None else remote.dense_timeout,
                api_key=remote.api_key, retry=remote.retry,
            )
    if config.tei is not None and config.tei.rerank_url and config.tei.rerank_model:
        from kb_api.rag_indexer.inference.providers.tei import TeiRerankClient

        remote = config.tei
        return TeiRerankClient(
            remote.rerank_url, remote.rerank_model,
            remote.rerank_timeout if remote.rerank_timeout is not None else remote.dense_timeout,
            retry=remote.retry,
        )
    return None


def _load_legacy_components(config: InferenceConfig):
    if config.siliconflow is not None:
        from kb_api.rag_indexer.inference.providers.siliconflow import SiliconFlowInferenceClient

        remote = config.siliconflow
        return SiliconFlowInferenceClient(
            base_url=remote.base_url, api_key=remote.api_key,
            dense_model=remote.dense_model, rerank_model=remote.rerank_model,
            dimensions=remote.dimensions, dense_timeout=remote.dense_timeout,
            rerank_timeout=remote.rerank_timeout, retry=remote.retry,
        )
    if config.tei is not None:
        from kb_api.rag_indexer.inference.providers.tei import TeiInferenceClient

        return TeiInferenceClient(config.tei)
    raise RuntimeError("inference provider is not configured")
