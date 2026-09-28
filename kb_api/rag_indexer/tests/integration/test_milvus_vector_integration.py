import uuid

import pytest


pytestmark = pytest.mark.integration


def _chunk(filename: str, content: str, chunk_index: int = 0, chunk_id: str | None = None) -> dict:
    return {
        "id": chunk_id or str(uuid.uuid4()),
        "content": content,
        "metadata": {"filename": filename, "chunk_index": chunk_index},
    }


class TestMilvusVectorClientIntegration:
    def test_describe_index_uses_cosine_metric(self, initialized_milvus_vector):
        vector = initialized_milvus_vector

        description = vector._client().describe_index(collection_name=vector._chunks_collection(), index_name=vector._dense_vector_field())

        assert description["metric_type"] == "COSINE"

    def test_file_reupload_replaces_old_chunks(self, initialized_milvus_vector):
        vector = initialized_milvus_vector
        file_id = "integrationfilereplace"

        chunks = [
            _chunk("replace.txt", "旧版知识 0", 0),
            _chunk("replace.txt", "旧版知识 1", 1),
        ]
        vector.add_file_chunks(chunks, file_id=file_id)
        vector.add_file_chunks(
            [
                {**chunks[0], "content": "第二版知识 0"},
            ],
            file_id=file_id,
        )

        docs = vector.list_chunks(file_ids=[file_id])["documents"]
        assert len(docs) == 1
        assert docs[0]["id"] == chunks[0]["id"]
        assert docs[0]["content"] == "第二版知识 0"

    def test_file_filter_limits_results_to_selected_files(self, initialized_milvus_vector):
        vector = initialized_milvus_vector

        vector.add_file_chunks([_chunk("a.txt", "A 文件知识")], file_id="integrationfilea")
        vector.add_file_chunks([_chunk("b.txt", "B 文件知识")], file_id="integrationfileb")
        vector.add_file_chunks([_chunk("c.txt", "C 文件知识")], file_id="integrationfilec")

        docs = vector.list_chunks(file_ids=["integrationfilea", "integrationfilec"])["documents"]
        filenames = {doc["metadata"]["filename"] for doc in docs}

        assert filenames == {"a.txt", "c.txt"}

    def test_list_chunks_uses_stable_three_key_cursor(self, initialized_milvus_vector):
        vector = initialized_milvus_vector

        vector.add_file_chunks(
            [
                _chunk("a.txt", "A0", 0, "a-0"),
                _chunk("a.txt", "A1", 1, "a-1"),
                _chunk("a.txt", "A2", 2, "a-2"),
            ],
            file_id="integrationfilea",
        )
        vector.add_file_chunks(
            [
                _chunk("b.txt", "B0", 0, "b-0"),
                _chunk("b.txt", "B1", 1, "b-1"),
                _chunk("b.txt", "B2", 2, "b-2"),
            ],
            file_id="integrationfileb",
        )

        first_page = vector.list_chunks(limit=4)
        second_page = vector.list_chunks(limit=4, cursor=first_page["next_cursor"])

        assert [document["id"] for document in first_page["documents"]] == ["a-0", "a-1", "a-2", "b-0"]
        assert [document["id"] for document in second_page["documents"]] == ["b-1", "b-2"]
        assert second_page["next_cursor"] is None
        assert second_page["has_more"] is False

    def test_dense_search_and_delete_file_chunks(self, initialized_milvus_vector):
        vector = initialized_milvus_vector
        file_id = "integrationfiledelete"

        vector.add_file_chunks(
            [
                _chunk("delete.txt", "人工智能 自然语言处理", 0),
                _chunk("delete.txt", "机器学习 深度学习", 1),
            ],
            file_id=file_id,
        )

        results = vector.search_dense("人工智能", 2, vector.build_file_filter([file_id]))
        assert results
        assert {result["metadata"]["file_id"] for result in results} == {file_id}

        assert vector.delete_file_chunks(file_id) == 2
        assert vector.get_total_chunks([file_id]) == 0
