from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimensions: int

    def __post_init__(self):
        if not self.provider.strip():
            raise ValueError("embedding provider is required")
        if not self.model.strip():
            raise ValueError("embedding model is required")
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be greater than 0")

class RoutedDenseClient:
    ready = True

    def __init__(self, clients: dict[EmbeddingSpec, object], *, default: EmbeddingSpec):
        if default not in clients:
            raise ValueError("embedding model is not configured")
        self._clients = dict(clients)
        self.default = default

    @property
    def model(self) -> str:
        return self.default.model

    @property
    def vector_size(self) -> int:
        return self.default.dimensions

    def embed_query(self, text: str) -> list[float]:
        return self._client().embed_query(text)

    def ping(self) -> bool:
        ping = getattr(self._client(), "ping", None)
        return bool(ping()) if callable(ping) else bool(getattr(self._client(), "ready", False))

    def close(self) -> None:
        closed = set()
        for client in self._clients.values():
            if id(client) in closed:
                continue
            closed.add(id(client))
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self.ready = False

    def _client(self):
        return self._clients[self.default]
