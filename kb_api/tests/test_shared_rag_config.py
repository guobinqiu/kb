import yaml


def test_entrypoints_read_shared_rag_configuration(tmp_path, monkeypatch):
    from kb_api.rag_indexer.core.loader import load_app_config
    from kb_api.rag_indexer.inference.config_loader import load_inference_config as load_index_inference
    from kb_api.rag_indexer.parser.config_loader import load_parser_config
    from kb_api.rag_retriever.common.config import load_vector_config
    from kb_api.rag_retriever.inference.config_loader import load_inference_config as load_query_inference

    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump({
        "vector_db": {"qdrant": {"enable": True, "base_url": "http://vector.example:6333"}},
        "inference": {"tei": {
            "enable": True,
            "dense": {"bge_m3": {
                "enable": True, "base_url": "http://embedding.example:80",
                "model_name": "BAAI/bge-m3", "dimensions": 1024,
            }},
        }},
        "parser": {"mineru": {"enable": True, "base_url": "http://parser.example:8000"}},
        "chunking": {"text": {"chunk_size": 800, "chunk_overlap": 60}},
    }), encoding="utf-8")
    monkeypatch.setenv("KB_CONFIG_FILE", str(path))

    index_config = load_app_config()
    query_config = load_vector_config(path)
    index_inference = load_index_inference()
    query_inference = load_query_inference()

    assert index_config.services.vector.base_url == query_config.base_url == "http://vector.example:6333"
    assert index_inference.tei.dense_url == query_inference.tei.dense_url == "http://embedding.example:80"
    assert index_inference.embedding.model == query_inference.embedding.model == "BAAI/bge-m3"
    assert index_inference.embedding.dimensions == query_inference.embedding.dimensions == 1024
    assert load_parser_config().mineru.base_url == "http://parser.example:8000"
    assert index_config.chunking.text.chunk_size == 800
