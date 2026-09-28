from __future__ import annotations

from contextlib import nullcontext

from fastapi import HTTPException

from kb_api.rag_indexer.inference.models import EmbeddingSpec


def embedding_spec(value) -> EmbeddingSpec | None:
    if value is None:
        return None
    if isinstance(value, EmbeddingSpec):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return EmbeddingSpec(
        provider=value["provider"],
        model=value["model"],
        dimensions=value["dimensions"],
    )


def resolve_embedding(state, requested=None) -> EmbeddingSpec:
    requested_spec = embedding_spec(requested)
    selected = requested_spec or getattr(state.inference_client, "embedding", None)
    if selected is None:
        raise HTTPException(400, "embedding is required")
    return selected


def embedding_scope(state, spec: EmbeddingSpec):
    scope = getattr(state.inference_client, "embedding_scope", None)
    return scope(spec) if callable(scope) else nullcontext()
