import pytest

from kb_api.rag_indexer.core.scope import collection_name_for_app


pytestmark = pytest.mark.unit


def test_app_id_accepts_40_characters_and_rejects_41():
    assert collection_name_for_app("a" * 40) == f"{'a' * 40}_chunks"

    with pytest.raises(ValueError, match="app_id"):
        collection_name_for_app("a" * 41)
