import pytest
import yaml
from kb_api.rag_indexer.parser.config_loader import load_parser_config


pytestmark = pytest.mark.unit


def _parser_yaml(raw):

    return yaml.safe_dump(raw)


def test_load_parser_config_selects_enabled_mineru(tmp_path):

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru_cloud": {
                    "enable": False,
                    "model_version": "vlm",
                    "enable_formula": True,
                    "enable_table": True,
                    "base_url": "https://mineru.net",
                    "timeout": 240,
                },
                "mineru": {"enable": True, "tier": "basic"},
            },
        }),
        encoding="utf-8",
    )

    config = load_parser_config(path)

    assert config.active == "mineru"
    assert config.mineru_cloud.model_version == "vlm"
    assert config.mineru_cloud.base_url == "https://mineru.net"
    assert config.mineru_cloud.timeout == 240
    assert config.mineru.tier == "basic"


def test_load_parser_config_rejects_no_enabled_backend(tmp_path):

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru_cloud": {"enable": False},
                "mineru": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="parser must enable exactly one backend"):
        load_parser_config(path)


def test_load_parser_config_rejects_multiple_enabled_backends(tmp_path):

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru_cloud": {"enable": True},
                "mineru": {"enable": True},
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="parser must enable exactly one backend"):
        load_parser_config(path)


def test_load_parser_config_uses_rag_config_file(tmp_path, monkeypatch):

    path = tmp_path / "rag.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "download_timeout": 77,
                "mineru_cloud": {"enable": False},
                "mineru": {"enable": True, "tier": "basic"},
            },
            "inference": {"unused": True},
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("KB_CONFIG_FILE", str(path))

    config = load_parser_config()

    assert config.active == "mineru"
    assert config.mineru.tier == "basic"
    assert config.download_timeout == 77
