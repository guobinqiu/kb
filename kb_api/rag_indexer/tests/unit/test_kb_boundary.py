import pytest
from fastapi import FastAPI

from kb_api.rag_indexer.core.api.routes import register_routes
from kb_api.rag_indexer.core.loader import load_config_file


pytestmark = pytest.mark.unit


def test_indexer_config_has_no_kb_owned_sections(tmp_path):
    import yaml

    path = tmp_path / "rag.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "services": {"vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"}},
                "vector_db": {"qdrant": {"enable": True, "base_url": "http://qdrant:6333"}},
            }
        ),
        encoding="utf-8",
    )

    config = load_config_file(path)



def test_indexer_does_not_register_legacy_kb_routes():
    app = FastAPI()
    register_routes(app)
    paths = {route.path for route in app.routes}

    assert "/api/rag/login" not in paths
    assert "/api/rag/apps" not in paths
    assert "/api/rag/files" not in paths
    assert "/api/v1/rag/search" not in paths
