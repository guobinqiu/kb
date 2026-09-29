import pytest
import yaml

from kb_api.rag_retriever.inference.config_loader import load_inference_config
from kb_api.rag_retriever.inference.service import load_inference_components


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("provider", "base_url", "api_key"), [
    ("siliconflow-cn", "https://api.siliconflow.cn/v1", "cn-test-key"),
    ("siliconflow-intl", "https://api.siliconflow.com/v1", "intl-test-key"),
])
def test_siliconflow_variants_share_provider(tmp_path, monkeypatch, provider, base_url, api_key):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "cn-test-key")
    monkeypatch.setenv("SILICONFLOW_INTL_API_KEY", "intl-test-key")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"inference": {provider: {
        "enable": True,
        "base_url": base_url,
        "retry": {"max_attempts": 3, "interval_seconds": 0.5},
        "dense": {"qwen": {
            "enable": True,
            "model_name": "Qwen/Qwen3-Embedding-0.6B",
            "dimensions": 1024,
            "timeout": 30,
        }},
        "rerank": {"qwen": {
            "enable": True,
            "model_name": "Qwen/Qwen3-Reranker-0.6B",
            "timeout": 30,
        }},
    }}}), encoding="utf-8")

    config = load_inference_config(path)

    assert config.siliconflow is not None
    assert config.siliconflow.base_url == base_url
    assert config.siliconflow.api_key == api_key
    assert config.siliconflow.dense_model == "Qwen/Qwen3-Embedding-0.6B"
    assert config.siliconflow.rerank_model == "Qwen/Qwen3-Reranker-0.6B"
    assert config.tei is None


@pytest.mark.parametrize("enabled", [True, False])
def test_siliconflow_rerank_enable_controls_loaded_client(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "test-key")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"inference": {"siliconflow-cn": {
        "enable": True,
        "base_url": "https://api.siliconflow.cn/v1",
        "dense": {"dense": {"enable": True, "model_name": "dense"}},
        "rerank": {"rerank": {"enable": enabled, "model_name": "rerank"}},
    }}}), encoding="utf-8")
    config = load_inference_config(path)
    client = load_inference_components(config)
    try:
        assert client.dense.model == "dense"
        assert (client.rerank is not None) is enabled
        assert client.sparse is None
    finally:
        client.close()


def test_load_inference_config_uses_rag_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "test-key")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"inference": {"siliconflow-cn": {
        "enable": True,
        "base_url": "https://api.siliconflow.cn/v1",
        "dense": {"dense": {"enable": True, "model_name": "dense"}},
    }}}), encoding="utf-8")
    monkeypatch.setenv("KB_CONFIG_FILE", str(path))

    config = load_inference_config()

    assert config.siliconflow is not None
    assert config.siliconflow.dense_model == "dense"


def test_inference_config_exposes_active_embedding(tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "test-key")
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump({"inference": {
        "siliconflow-cn": {
            "enable": True,
            "base_url": "https://api.siliconflow.cn/v1",
            "dense": {
                "qwen_small": {
                    "enable": True,
                    "model_name": "Qwen/Qwen3-Embedding-0.6B",
                    "dimensions": 1024,
                },
                    "qwen_large": {
                        "enable": False,
                    "model_name": "Qwen/Qwen3-Embedding-4B",
                    "dimensions": 2560,
                },
            },
        },
    }}), encoding="utf-8")

    config = load_inference_config(path)

    assert sorted((item.provider, item.model, item.dimensions) for item in config.dense_models) == [
        ("siliconflow-cn", "Qwen/Qwen3-Embedding-0.6B", 1024),
    ]
