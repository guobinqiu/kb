import math
import os
import uuid

import pytest
import yaml

from kb_api.rag_indexer.clients.vector.milvus import MilvusVectorClient
from kb_api.rag_indexer.clients.vector.qdrant import QdrantVectorClient
from kb_api.rag_indexer.tests.conftest import DeterministicDense
from kb_api.rag_indexer.common.config import QdrantQuantizationConfig
from kb_api.rag_indexer.common.paths import PROJECT_ROOT


pytestmark = pytest.mark.integration


@pytest.fixture
def cloud_services():
    config_path = PROJECT_ROOT / "kb_api" / "config" / "rag.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))["vector_db"]


@pytest.mark.parametrize("provider", ["qdrant_cloud", "milvus_cloud"])
def test_cloud_vector_collection_lifecycle(cloud_services, provider):
    config = cloud_services[provider]
    dense = DeterministicDense()
    dense.start()
    if provider == "qdrant_cloud":
        vector = QdrantVectorClient(
            dense=dense,
            url=config["base_url"],
            query_timeout=config["query_timeout"],
            write_timeout=config["write_timeout"],
            init_timeout=config["init_timeout"],
            drop_timeout=config["drop_timeout"],
            api_key=os.environ["QDRANT_CLOUD_API_KEY"],
            quantization=QdrantQuantizationConfig(**config["quantization"]),
        )
    else:
        vector = MilvusVectorClient(
            dense=dense,
            uri=config["base_url"],
            query_timeout=config["query_timeout"],
            write_timeout=config["write_timeout"],
            init_timeout=config["init_timeout"],
            drop_timeout=config["drop_timeout"],
            token=os.environ["MILVUS_CLOUD_TOKEN"],
        )
    app_id = f"cloud_{uuid.uuid4().hex}"
    file_id = str(uuid.uuid4())
    chunks = [
        {"id": str(uuid.uuid4()), "content": text, "metadata": {"filename": "cloud.txt", "chunk_index": index}}
        for index, text in enumerate(["Paris is the capital of France.", "Bread is baked in an oven."])
    ]
    try:
        vector.start()
        vector.ensure_app_collection(app_id)
        assert vector.app_collection_exists(app_id)
        with vector.app_scope(app_id):
            assert vector.add_file_chunks(chunks, file_id) == 2
            assert vector.get_total_chunks([file_id]) == 2
            results = vector.search_dense(chunks[0]["content"], 2, vector.build_file_filter([file_id]))
            assert len(results) == 2
            assert results[0]["id"] == chunks[0]["id"]
            assert {result["content"] for result in results} == {chunk["content"] for chunk in chunks}
            assert {result["metadata"]["file_id"] for result in results} == {file_id}
            assert {result["metadata"]["filename"] for result in results} == {"cloud.txt"}
            stored = vector.get_dense_vector(chunks[0]["id"])
            expected = dense.embed_query(chunks[0]["content"])
            assert len(stored) == dense.vector_size
            stored_norm = math.sqrt(sum(value * value for value in stored))
            expected_norm = math.sqrt(sum(value * value for value in expected))
            assert [value / stored_norm for value in stored] == pytest.approx([value / expected_norm for value in expected])
            replacement = {**chunks[0], "content": "Paris is the largest city in France."}
            assert vector.add_file_chunks([replacement], file_id) == 1
            assert vector.get_total_chunks([file_id]) == 1
            documents = vector.list_chunks(file_ids=[file_id])["documents"]
            assert len(documents) == 1
            assert documents[0]["id"] == chunks[0]["id"]
            assert documents[0]["content"] == replacement["content"]
            assert vector.delete_file_chunks(file_id) == 1
            assert vector.get_total_chunks([file_id]) == 0
            assert vector.search_dense(chunks[0]["content"], 2, vector.build_file_filter([file_id])) == []
    finally:
        try:
            vector.drop_app_collection(app_id)
            assert not vector.app_collection_exists(app_id)
        finally:
            try:
                vector.close()
            finally:
                dense.stop()
