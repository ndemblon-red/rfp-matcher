"""Tests for the embedding pipeline in analysis.py."""
import math
from unittest.mock import MagicMock, patch


# ── Cosine similarity ─────────────────────────────────────────────────────────

def test_cosine_similarity_identical_vectors():
    from analysis import _cosine_similarity
    v = [1.0, 2.0, 3.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors():
    from analysis import _cosine_similarity
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6


def test_cosine_similarity_opposite_vectors():
    from analysis import _cosine_similarity
    assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-6


def test_cosine_similarity_zero_vector_returns_zero():
    from analysis import _cosine_similarity
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert _cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0


def test_cosine_similarity_known_value():
    from analysis import _cosine_similarity
    # [1,1] · [1,0] = 1; |[1,1]| = sqrt(2); |[1,0]| = 1  →  cos = 1/sqrt(2)
    result = _cosine_similarity([1.0, 1.0], [1.0, 0.0])
    assert abs(result - 1.0 / math.sqrt(2)) < 1e-6


# ── Serialisation ─────────────────────────────────────────────────────────────

def test_serialize_deserialize_roundtrip():
    from analysis import _serialize_embedding, _deserialize_embedding
    original = [0.1, 0.2, 0.3, -0.5, 1.0]
    blob = _serialize_embedding(original)
    assert isinstance(blob, bytes)
    recovered = _deserialize_embedding(blob)
    assert len(recovered) == len(original)
    for a, b in zip(original, recovered):
        assert abs(a - b) < 1e-5  # float32 precision


def test_serialize_produces_correct_byte_length():
    from analysis import _serialize_embedding
    # float32 = 4 bytes per element
    blob = _serialize_embedding([0.0] * 1536)
    assert len(blob) == 1536 * 4


# ── Embedding text builders ───────────────────────────────────────────────────

def test_build_rfp_embedding_text_all_fields():
    from analysis import _build_rfp_embedding_text
    brief = {
        "objective": "Reduce fleet delivery costs.",
        "challenges": ["High fuel costs", "Inefficient routing"],
        "capabilities_needed": ["predictive analytics", "route optimisation"],
        "context": {"industry": "Logistics", "scale": "", "constraints": ""},
    }
    text = _build_rfp_embedding_text(brief)
    assert "Reduce fleet delivery costs." in text
    assert "High fuel costs" in text
    assert "predictive analytics" in text


def test_build_rfp_embedding_text_empty_lists():
    from analysis import _build_rfp_embedding_text
    text = _build_rfp_embedding_text({"objective": "Something.", "challenges": [], "capabilities_needed": []})
    assert "Something." in text
    assert text.strip()


def test_build_rfp_embedding_text_missing_keys():
    from analysis import _build_rfp_embedding_text
    text = _build_rfp_embedding_text({})
    assert text == ""


def test_build_cs_embedding_text_uses_sections():
    from analysis import _build_cs_embedding_text
    content = "Challenge: Reduce costs.\nApproach: Use ML.\nResults: 20% savings."
    text = _build_cs_embedding_text(content)
    assert "Reduce costs." in text
    assert "Use ML." in text
    assert "20% savings." in text


def test_build_cs_embedding_text_fallback_to_raw():
    from analysis import _build_cs_embedding_text
    content = "A project about demand planning with no structured sections."
    text = _build_cs_embedding_text(content)
    assert "demand planning" in text


def test_build_cs_embedding_text_empty_string():
    from analysis import _build_cs_embedding_text
    assert _build_cs_embedding_text("") == ""


# ── generate_embedding ────────────────────────────────────────────────────────

def test_generate_embedding_calls_openai_and_returns_list():
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])]
    )
    with patch("analysis._get_openai_client", return_value=mock_client):
        from analysis import generate_embedding
        result = generate_embedding("some rfp text")

    assert result == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input="some rfp text",
    )


def test_generate_embedding_raises_on_missing_key():
    import os
    original = os.environ.pop("OPENAI_API_KEY", None)
    # Reset the cached client so the key check runs.
    import analysis as analysis_mod
    saved = analysis_mod._openai_client
    analysis_mod._openai_client = None
    try:
        from analysis import generate_embedding
        try:
            generate_embedding("text")
            assert False, "Expected RuntimeError"
        except RuntimeError as e:
            assert "OPENAI_API_KEY" in str(e)
    finally:
        analysis_mod._openai_client = saved
        if original is not None:
            os.environ["OPENAI_API_KEY"] = original


# ── store_embeddings ──────────────────────────────────────────────────────────

def test_store_embeddings_generates_for_missing():
    candidates = [
        {"id": 1, "title": "Route Opt", "slide_content": "Challenge: Cost\nApproach: ML\nResults: 20%"},
    ]
    mock_embedding = [0.1] * 10

    with patch("db.get_case_studies_without_embeddings", return_value=candidates), \
         patch("db.store_case_study_embedding") as mock_store, \
         patch("analysis.generate_embedding", return_value=mock_embedding):
        from analysis import store_embeddings
        stats = store_embeddings()

    assert stats["generated"] == 1
    assert stats["failed"] == 0
    mock_store.assert_called_once()
    args = mock_store.call_args[0]
    assert args[0] == 1               # case_id
    assert args[2] == "text-embedding-3-small"


def test_store_embeddings_skips_empty_content():
    candidates = [{"id": 1, "title": "Empty", "slide_content": ""}]

    with patch("db.get_case_studies_without_embeddings", return_value=candidates), \
         patch("db.store_case_study_embedding") as mock_store, \
         patch("analysis.generate_embedding") as mock_gen:
        from analysis import store_embeddings
        stats = store_embeddings()

    mock_gen.assert_not_called()
    mock_store.assert_not_called()
    assert stats["failed"] == 1


def test_store_embeddings_handles_api_failure():
    candidates = [{"id": 1, "title": "Route Opt", "slide_content": "Challenge: X"}]

    with patch("db.get_case_studies_without_embeddings", return_value=candidates), \
         patch("db.store_case_study_embedding"), \
         patch("analysis.generate_embedding", side_effect=RuntimeError("API error")):
        from analysis import store_embeddings
        stats = store_embeddings()

    assert stats["failed"] == 1
    assert stats["generated"] == 0


def test_store_embeddings_returns_zero_when_all_embedded():
    with patch("db.get_case_studies_without_embeddings", return_value=[]):
        from analysis import store_embeddings
        stats = store_embeddings()

    assert stats == {"generated": 0, "failed": 0}


# ── match_case_studies embedding integration ──────────────────────────────────

_MOCK_BRIEF = {
    "objective": "Optimise fleet routes.",
    "challenges": ["High costs"],
    "capabilities_needed": ["route optimisation"],
    "context": {"industry": "Logistics", "scale": "", "constraints": ""},
}

_MOCK_MATCH_RESPONSE = {
    "text": '[{"id": 1, "score": 80, "explanation": "Key difference: X. Strong match.", "matched_caps": []}]',
    "input_tokens": 500,
    "output_tokens": 100,
    "truncated": False,
}


def _make_cs_with_embedding(cs_id, title, slide_content, embedding):
    from analysis import _serialize_embedding
    return {
        "id": cs_id,
        "title": title,
        "industry_full": "Test",
        "engagement_type": "Machine Learning",
        "has_video": 0,
        "slide_content": slide_content,
        "embedding": _serialize_embedding(embedding),
    }


def test_match_case_studies_uses_embedding_preselection():
    """With 12 case studies (10 similar, 2 orthogonal), only the top-10 reach Claude."""
    rfp_emb = [1.0, 0.0]

    # First 10: similar to RFP (positive x); last 2: orthogonal
    case_studies = [
        _make_cs_with_embedding(i, f"CS {i}", f"Challenge: C{i}", [1.0, 0.0])
        for i in range(1, 11)
    ]
    case_studies.append(_make_cs_with_embedding(11, "Low CS 11", "Challenge: X", [0.0, 1.0]))
    case_studies.append(_make_cs_with_embedding(12, "Low CS 12", "Challenge: Y", [0.0, 1.0]))

    captured = {}

    def capture_claude(system, user, **kwargs):
        captured["user"] = user
        return _MOCK_MATCH_RESPONSE

    with patch("analysis.generate_embedding", return_value=rfp_emb), \
         patch("analysis._call_claude", side_effect=capture_claude):
        from analysis import match_case_studies
        match_case_studies("rfp text", case_studies, brief=_MOCK_BRIEF)

    assert '"Low CS 11"' not in captured["user"]
    assert '"Low CS 12"' not in captured["user"]


def test_match_case_studies_falls_back_without_embeddings():
    """When no case studies have embeddings, all are forwarded to Claude."""
    case_studies = [
        {"id": i, "title": f"CS {i}", "industry_full": "T", "engagement_type": "ML",
         "has_video": 0, "slide_content": f"Challenge: C{i}"}
        for i in range(1, 4)
    ]

    captured = {}

    def capture_claude(system, user, **kwargs):
        captured["user"] = user
        return {
            "text": '[{"id": 1, "score": 80, "explanation": "Key diff: X. Good.", "matched_caps": []}]',
            "input_tokens": 100, "output_tokens": 50, "truncated": False,
        }

    with patch("analysis._call_claude", side_effect=capture_claude):
        from analysis import match_case_studies
        match_case_studies("rfp text", case_studies)

    for i in range(1, 4):
        assert f'"CS {i}"' in captured["user"]


def test_match_case_studies_selects_highest_similarity():
    """The case study with identical embedding to the RFP should rank first in the payload."""
    rfp_emb = [1.0, 0.0, 0.0]
    case_studies = [
        _make_cs_with_embedding(1, "Perfect Match", "Challenge: X", [1.0, 0.0, 0.0]),
        _make_cs_with_embedding(2, "Weak Match", "Challenge: Y", [0.0, 1.0, 0.0]),
    ]

    captured = {}

    def capture_claude(system, user, **kwargs):
        captured["user"] = user
        return _MOCK_MATCH_RESPONSE

    with patch("analysis.generate_embedding", return_value=rfp_emb), \
         patch("analysis._call_claude", side_effect=capture_claude):
        from analysis import match_case_studies
        match_case_studies("rfp text", case_studies, brief=_MOCK_BRIEF)

    # "Perfect Match" must appear before "Weak Match" in the payload
    pos_perfect = captured["user"].find('"Perfect Match"')
    pos_weak = captured["user"].find('"Weak Match"')
    assert pos_perfect < pos_weak
