from kb_api.rag_retriever.core.scope import app_collection, collection_name_for_app, current_collection


def test_business_app_id_uses_expected_collection():
    app_id = "imsdom"
    expected = "imsdom_chunks"

    assert collection_name_for_app(app_id) == expected
    with app_collection(app_id):
        assert current_collection() == expected
