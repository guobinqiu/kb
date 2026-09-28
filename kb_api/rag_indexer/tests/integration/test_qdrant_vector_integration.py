import pytest
import uuid


pytestmark = pytest.mark.integration


def _chunk(filename: str, content: str, chunk_index: int = 0) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "metadata": {"filename": filename, "chunk_index": chunk_index},
    }


class TestQdrantVectorClientIntegration:
    def test_file_reupload_replaces_old_chunks(self, initialized_qdrant_vector):
        vector = initialized_qdrant_vector
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

    def test_file_filter_limits_results_to_selected_files(self, initialized_qdrant_vector):
        vector = initialized_qdrant_vector

        vector.add_file_chunks([_chunk("a.txt", "A 文件知识")], file_id="integrationfilea")
        vector.add_file_chunks([_chunk("b.txt", "B 文件知识")], file_id="integrationfileb")
        vector.add_file_chunks([_chunk("c.txt", "C 文件知识")], file_id="integrationfilec")

        docs = vector.list_chunks(file_ids=["integrationfilea", "integrationfilec"])["documents"]
        filenames = {doc["metadata"]["filename"] for doc in docs}

        assert filenames == {"a.txt", "c.txt"}

    def test_delete_file_chunks_returns_deleted_chunk_count(self, initialized_qdrant_vector):
        vector = initialized_qdrant_vector
        file_id = "integrationfiledelete"

        vector.add_file_chunks(
            [
                _chunk("delete.txt", "待删除知识 0"),
                _chunk("delete.txt", "待删除知识 1"),
            ],
            file_id=file_id,
        )

        assert vector.delete_file_chunks(file_id) == 2
        assert vector.get_total_chunks([file_id]) == 0
