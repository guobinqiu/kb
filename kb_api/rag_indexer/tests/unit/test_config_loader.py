import pytest
from kb_api.rag_indexer.core.loader import load_app_config
import yaml
from kb_api.rag_indexer.core.loader import load_config_file
from kb_api.rag_indexer.core import loader


pytestmark = pytest.mark.unit


def test_vector_fixture_loads_index_configuration(vector_test_env):

    assert load_app_config().services.vector.provider == "qdrant"


def _base_config(vector: str = "qdrant") -> dict:
    vector_urls = {
        "qdrant": "http://qdrant:6333",
        "milvus": "http://milvus:19530",
        "qdrant_cloud": "https://qdrant_cloud.example",
        "milvus_cloud": "https://milvus_cloud.example",
    }
    return {
        "storage": {"endpoint_url": "https://storage.example:9000", "bucket": "documents", "presign_timeout": 44},
        "vector_db": {vector: {
            "enable": True,
            "base_url": vector_urls[vector],
            "query_timeout": 10,
            "write_timeout": 60,
            "init_timeout": 120,
            "drop_timeout": 180,
        }},
    }


def test_load_config_file_reads_qdrant_config(tmp_path):

    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(_base_config("qdrant")), encoding="utf-8")
    config = load_config_file(path)

    assert config.services.vector.provider == "qdrant"
    assert config.services.vector.base_url == "http://qdrant:6333"
    assert config.services.vector.query_timeout == 10
    assert config.services.vector.write_timeout == 60
    assert config.services.vector.init_timeout == 120
    assert config.services.vector.drop_timeout == 180
    assert config.name == "rag"
    assert config.storage.endpoint_url == "https://storage.example:9000"


def test_load_config_file_reads_service_bound_milvus_config(tmp_path):

    path = tmp_path / "milvus.yaml"
    path.write_text(yaml.safe_dump(_base_config("milvus")), encoding="utf-8")
    config = load_config_file(path)

    assert config.services.vector.provider == "milvus"
    assert config.services.vector.base_url == "http://milvus:19530"


@pytest.mark.parametrize("selected,provider", [("qdrant_cloud", "qdrant"), ("milvus_cloud", "milvus")])
def test_cloud_vector_selection_keeps_cloud_endpoint(tmp_path, monkeypatch, selected, provider):

    monkeypatch.setenv("MILVUS_CLOUD_TOKEN", "cloud-token")
    monkeypatch.setenv("QDRANT_CLOUD_API_KEY", "cloud-key")
    raw = _base_config()
    for name in ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud"):
        raw["vector_db"][name] = {
            "enable": name == selected,
            "base_url": f"https://{name}.example" if name.endswith("_cloud") else f"http://{name}:6333",
        }
    path = tmp_path / "cloud.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config_file(path)

    assert config.services.vector.provider == provider
    assert config.services.vector.base_url == f"https://{selected}.example"
    assert config.services.vector.token == ("cloud-token" if provider == "milvus" else None)
    assert config.services.vector.api_key == ("cloud-key" if provider == "qdrant" else None)


def test_load_app_config_uses_project_yaml_by_default(tmp_path, monkeypatch):

    path = tmp_path / "config/rag.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(_base_config("milvus")), encoding="utf-8")
    monkeypatch.setattr(loader, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("KB_CONFIG_FILE", raising=False)
    config = loader.load_app_config()

    assert config.name == "rag"
    assert config.services.vector.provider == "milvus"


def test_load_config_file_selects_one_enabled_vector_backend(tmp_path):

    raw = _base_config("qdrant")
    raw["vector_db"]["qdrant"] = {"enable": False}
    raw["vector_db"]["milvus"] = {"enable": True, "base_url": "http://milvus:19530"}
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config_file(path)

    assert config.services.vector.provider == "milvus"
    assert config.services.vector.base_url == "http://milvus:19530"
