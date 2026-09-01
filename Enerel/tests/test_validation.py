import pytest

from validation import DOC_TYPES, ValidationError, validate_document_payload, validate_search_payload


def make_payload(**overrides):
    payload = {
        "title": "Understanding Dollar-Cost Averaging",
        "source": "Investopedia",
        "doc_type": "guide",
        "published_on": "2025-11-03",
        "body_text": "Dollar-cost averaging is an investment strategy...",
    }
    payload.update(overrides)
    return payload


def test_valid_payload_is_accepted_and_trimmed():
    clean = validate_document_payload(make_payload(title="  Padded Title  "))

    assert clean["title"] == "Padded Title"
    assert clean["doc_type"] == "guide"
    assert clean["published_on"] == "2025-11-03"


def test_missing_title_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_document_payload(make_payload(title=""))

    assert any("title" in message for message in exc_info.value.errors)


def test_invalid_doc_type_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_document_payload(make_payload(doc_type="not-a-real-type"))

    message = str(exc_info.value)
    assert "doc_type" in message
    for doc_type in DOC_TYPES:
        assert doc_type in message


def test_empty_body_text_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_document_payload(make_payload(body_text="   "))

    assert any("body_text" in message for message in exc_info.value.errors)


def test_malformed_published_on_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_document_payload(make_payload(published_on="03/11/2025"))

    assert any("published_on" in message for message in exc_info.value.errors)


def test_published_on_is_optional():
    clean = validate_document_payload(make_payload(published_on=None))

    assert clean["published_on"] is None


def test_source_is_optional():
    payload = make_payload()
    del payload["source"]

    clean = validate_document_payload(payload)

    assert clean["source"] is None


def test_non_dict_payload_is_rejected():
    with pytest.raises(ValidationError):
        validate_document_payload("not a dict")


def test_all_doc_types_are_individually_valid():
    for doc_type in DOC_TYPES:
        clean = validate_document_payload(make_payload(doc_type=doc_type))
        assert clean["doc_type"] == doc_type


# --------------------------------------------------------------------------
# search payload
# --------------------------------------------------------------------------

def test_search_payload_defaults_top_k_to_5():
    clean = validate_search_payload({"query": "inflation"})

    assert clean["top_k"] == 5


def test_search_payload_accepts_custom_top_k():
    clean = validate_search_payload({"query": "inflation", "top_k": 3})

    assert clean["top_k"] == 3


def test_search_payload_rejects_empty_query():
    with pytest.raises(ValidationError) as exc_info:
        validate_search_payload({"query": "   "})

    assert any("query" in message for message in exc_info.value.errors)


@pytest.mark.parametrize("bad_top_k", [0, 21, -1, "5", 3.5, True])
def test_search_payload_rejects_out_of_range_top_k(bad_top_k):
    with pytest.raises(ValidationError) as exc_info:
        validate_search_payload({"query": "inflation", "top_k": bad_top_k})

    assert any("top_k" in message for message in exc_info.value.errors)
