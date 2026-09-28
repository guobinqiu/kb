import pytest


pytestmark = pytest.mark.unit


def test_config_payload_includes_rerank_defaults_without_kb_owned_config():
    from kb_api.rag_indexer.common.config import parse_app_config
    from kb_api.rag_indexer.core.api.services.config import config_payload

    config = parse_app_config({
        "services": {
            "vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"},
        },
    })
    state = type(
        "State",
        (),
        {
            "config": config,
            "config_name": "qdrant",
            "vector_client": object(),
        },
    )()

    payload = config_payload(state)

    assert "top_k" not in payload
    assert "rerank" not in payload
    assert "database" not in payload["services"]
    assert payload["capabilities"]["app_management"] is False
    assert payload["capabilities"]["file_records"] is False
