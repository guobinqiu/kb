import pytest


pytestmark = pytest.mark.unit


def test_close_vector_closes_qdrant_client_and_clears_vector_cache():
    from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient

    class FakeDense:
        ready = True

        def embed_query(self, text):
            return [0.1, 0.2]

    class FakeClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeClient()
    vector = QdrantVectorClient(dense=FakeDense())
    vector.client = fake
    vector._ready = True

    vector.stop()

    assert fake.closed is True
    assert vector.client is None
    assert vector.ready is False
