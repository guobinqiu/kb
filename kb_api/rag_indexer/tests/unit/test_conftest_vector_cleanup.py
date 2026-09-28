import pytest


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("error", [None, ConnectionError("connection refused"), RuntimeError("authentication failed")])
def test_qdrant_availability_closes_client(error, monkeypatch):
    from kb_api.rag_indexer.tests import conftest

    class Client:
        closed = False

        def get_collections(self):
            if error is not None:
                raise error

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(conftest, "_make_qdrant_client", lambda url: client)

    if isinstance(error, RuntimeError):
        with pytest.raises(RuntimeError, match="authentication failed"):
            conftest._qdrant_available("http://qdrant:6333")
    else:
        assert conftest._qdrant_available("http://qdrant:6333") is (error is None)
    assert client.closed


def test_drop_vector_collection_uses_configured_vector(monkeypatch):
    from kb_api.rag_indexer.tests import conftest

    calls = []

    monkeypatch.setattr(conftest, "_drop_qdrant_collection", lambda url, name: calls.append(("qdrant", url, name)))
    monkeypatch.setattr(conftest, "_drop_milvus_collection", lambda uri, name: calls.append(("milvus", uri, name)))

    conftest._drop_vector_collection(
        "milvus",
        "test_run",
        endpoint="http://milvus:19530",
    )

    assert calls == [("milvus", "http://milvus:19530", "test_run_chunks")]


def test_milvus_skip_helper_skips_when_connection_fails(monkeypatch):
    from kb_api.rag_indexer.tests import conftest

    monkeypatch.setattr(conftest, "_milvus_available", lambda uri: False)

    with pytest.raises(pytest.skip.Exception):
        conftest._skip_if_milvus_unavailable("http://milvus:19530")


def test_qdrant_skip_helper_skips_when_connection_fails(monkeypatch):
    from kb_api.rag_indexer.tests import conftest

    monkeypatch.setattr(conftest, "_qdrant_available", lambda url: False)

    with pytest.raises(pytest.skip.Exception):
        conftest._skip_if_qdrant_unavailable("http://qdrant:6333")


def test_milvus_available_does_not_hide_non_connection_errors(monkeypatch):
    from kb_api.rag_indexer.tests import conftest

    def raise_non_connection_error(uri):
        raise RuntimeError("authentication failed")

    monkeypatch.setattr(conftest, "_make_milvus_client", raise_non_connection_error)

    with pytest.raises(RuntimeError, match="authentication failed"):
        conftest._milvus_available("http://milvus:19530")
