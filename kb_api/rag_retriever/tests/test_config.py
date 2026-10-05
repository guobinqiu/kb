import pytest
import yaml

from kb_api.rag_retriever.common.config import (
    QdrantQuantizationConfig,
    RetryConfig,
    VectorConfig,
    load_search_config,
    load_vector_config,
)


pytestmark = pytest.mark.unit


def test_search_config_reads_fetch_k(tmp_path):
    config_path = tmp_path / "rag.yaml"
    config_path.write_text(yaml.safe_dump({"search": {"fetch_k": 24}}), encoding="utf-8")

    assert load_search_config(config_path).fetch_k == 24


@pytest.mark.parametrize("backend,provider,secret_env,secret_field", [
    ("qdrant", "qdrant", "QDRANT_API_KEY", "api_key"),
    ("qdrant_cloud", "qdrant", "QDRANT_CLOUD_API_KEY", "api_key"),
    ("milvus", "milvus", "MILVUS_TOKEN", "token"),
    ("milvus_cloud", "milvus", "MILVUS_CLOUD_TOKEN", "token"),
])
def test_vector_config_selects_backend_and_environment_secret(tmp_path, monkeypatch, backend, provider, secret_env, secret_field):
    for name in ("QDRANT_API_KEY", "QDRANT_CLOUD_API_KEY", "MILVUS_TOKEN", "MILVUS_CLOUD_TOKEN"):
        monkeypatch.setenv(name, f"secret-for-{name}")
    config_path = tmp_path / "rag.yaml"
    config_path.write_text(yaml.safe_dump({"vector_db": {
        backend: {
            "enable": True,
            "base_url": "https://vector.example.test",
            "api_key": "ignored-yaml-key",
            "token": "ignored-yaml-token",
        },
        "milvus" if backend.startswith("qdrant") else "qdrant": {
            "enable": False,
            "base_url": "https://disabled.example.test",
        },
    }}), encoding="utf-8")
    monkeypatch.setenv("KB_CONFIG_FILE", str(config_path))

    config = load_vector_config()

    assert isinstance(config, VectorConfig)
    assert config.provider == provider
    assert config.base_url == "https://vector.example.test"
    assert getattr(config, secret_field) == f"secret-for-{secret_env}"
    assert getattr(config, "token" if secret_field == "api_key" else "api_key") is None


@pytest.mark.parametrize("timeout,expected", [(None, 30), ("17", 17)])
def test_vector_config_timeouts_fall_back_to_general_timeout(tmp_path, timeout, expected):
    selected = {"enable": True, "base_url": "http://vector.example.test"}
    if timeout is not None:
        selected["timeout"] = timeout
    config_path = tmp_path / "rag.yaml"
    config_path.write_text(yaml.safe_dump({"vector_db": {"qdrant": selected}}), encoding="utf-8")

    config = load_vector_config(config_path)

    assert (config.timeout, config.query_timeout, config.init_timeout, config.drop_timeout) == (expected,) * 4
    assert config.retry == RetryConfig()
    assert config.quantization is None


@pytest.mark.parametrize("backend", ["qdrant", "milvus"])
def test_vector_config_reads_bm25_switch(tmp_path, backend):
    config_path = tmp_path / "rag.yaml"
    config_path.write_text(yaml.safe_dump({"vector_db": {backend: {
        "enable": True, "base_url": "http://vector.example.test", "bm25": False,
    }}}), encoding="utf-8")

    assert load_vector_config(config_path).bm25 is False


def test_vector_config_reads_explicit_timeouts_retry_and_quantization(tmp_path, monkeypatch):
    monkeypatch.delenv("QDRANT_CLOUD_API_KEY", raising=False)
    config_path = tmp_path / "rag.yaml"
    config_path.write_text(yaml.safe_dump({"vector_db": {"qdrant_cloud": {
        "enable": True,
        "base_url": "https://vector.example.test",
        "api_key": "ignored-yaml-key",
        "timeout": "17",
        "query_timeout": "4",
        "write_timeout": "8",
        "init_timeout": "12",
        "drop_timeout": "16",
        "retry": {"max_attempts": 0, "interval_seconds": -1},
        "quantization": {"enable": "yes", "type": "int8", "quantile": "0.99", "always_ram": "off"},
    }}}), encoding="utf-8")

    config = load_vector_config(config_path)

    assert config.provider == "qdrant"
    assert (config.timeout, config.query_timeout, config.init_timeout, config.drop_timeout) == (17, 4, 12, 16)
    assert config.retry == RetryConfig(max_attempts=1, interval_seconds=0.0)
    assert config.quantization == QdrantQuantizationConfig(enable=True, type="int8", quantile=0.99, always_ram=False)
    assert config.api_key is None
