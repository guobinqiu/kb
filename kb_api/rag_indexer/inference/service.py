from __future__ import annotations

from contextlib import nullcontext

from kb_api.rag_indexer.inference.config_loader import DenseModelConfig, InferenceConfig, load_inference_config
from kb_api.rag_indexer.inference.models import EmbeddingSpec, RoutedDenseClient
from kb_api.rag_indexer.inference.providers import siliconflow, tei


class InferenceComponents:
    def __init__(self, dense, *, embedding: EmbeddingSpec | None = None):
        self.dense = dense
        self.embedding = embedding
        self.ready = True

    def embedding_scope(self, spec: EmbeddingSpec):
        use = getattr(self.dense, "use", None)
        return use(spec) if callable(use) else nullcontext()

    def ping(self) -> bool:
        ping = getattr(self.dense, "ping", None)
        return self.ready and (bool(ping()) if callable(ping) else bool(getattr(self.dense, "ready", False)))

    def close(self) -> None:
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
            embedding=config.embedding,
        )
    return _load_legacy_components(config)


def _build_dense(config: DenseModelConfig):
    if config.provider.startswith("siliconflow-"):
        return siliconflow.SiliconFlowDenseClient(
            config.base_url, model=config.model, timeout=config.timeout, api_key=config.api_key,
            dimensions=config.dimensions, retry=config.retry,
        )
    if config.provider == "tei":
        return tei.TeiDenseClient(
            config.base_url, config.model, config.timeout,
            dimensions=config.dimensions, retry=config.retry,
            batch_size=config.batch_size,
        )
    raise ValueError(f"unsupported inference provider: {config.provider}")


def _load_legacy_components(config: InferenceConfig):
    if config.siliconflow is not None:
        remote = config.siliconflow
        return InferenceComponents(siliconflow.SiliconFlowDenseClient(
            base_url=remote.base_url, api_key=remote.api_key,
            model=remote.dense_model, dimensions=remote.dimensions,
            timeout=remote.dense_timeout, retry=remote.retry,
        ))
    if config.tei is not None:
        remote = config.tei
        return InferenceComponents(tei.TeiDenseClient(
            remote.dense_url, remote.dense_model, remote.dense_timeout,
            dimensions=remote.dimensions, retry=remote.retry,
            batch_size=remote.batch_size,
        ))
    raise RuntimeError("inference provider is not configured")
