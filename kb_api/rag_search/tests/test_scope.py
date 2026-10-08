import pytest
from pydantic import ValidationError

from kb_api.rag_search.core.scope import app_collection, collection_name_for_app, current_collection
from kb_api.rag_search.schemas import SearchRequest


def test_business_app_id_uses_expected_collection():
    app_id = "imsdom"
    expected = "imsdom_chunks"

    assert collection_name_for_app(app_id) == expected
    with app_collection(app_id):
        assert current_collection() == expected


def test_app_id_accepts_40_characters_and_rejects_41():
    assert collection_name_for_app("a" * 40) == f"{'a' * 40}_chunks"

    with pytest.raises(ValueError, match="app_id"):
        collection_name_for_app("a" * 41)

    with pytest.raises(ValidationError):
        SearchRequest(query="policy", app_id="a" * 41, workspace_ids=["workspace"])
