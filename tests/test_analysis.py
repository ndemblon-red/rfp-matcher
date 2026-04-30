"""Tests for analysis.py — _extract_sections and match_case_studies."""
from unittest.mock import patch


# ── Shared test data ──────────────────────────────────────────────────────────

SAMPLE_CASE_STUDIES = [
    {
        "id": 1,
        "title": "Route Optimisation",
        "industry_full": "Logistics",
        "engagement_type": "Machine Learning",
        "has_video": 0,
        "slide_content": (
            "Challenge: Reduce delivery costs across a large fleet.\n"
            "Approach: ML routing model trained on historical trips.\n"
            "Results: 20% cost reduction across 500 vehicles."
        ),
    },
    {
        "id": 2,
        "title": "AI Diagnosis",
        "industry_full": "Healthcare",
        "engagement_type": "Computer Vision",
        "has_video": 1,
        "slide_content": (
            "Challenge: Radiology backlog causing delays.\n"
            "Approach: Computer vision model for image triage.\n"
            "Results: 40% reduction in diagnosis time."
        ),
    },
]

_MOCK_CLAUDE_RESPONSE = {
    "text": (
        '[{"id": 1, "score": 85, "explanation": "Strong match on cost optimisation."}, '
        '{"id": 2, "score": 42, "explanation": "Partial match on AI approach."}]'
    ),
    "input_tokens": 500,
    "output_tokens": 100,
    "truncated": False,
}


# ── _extract_sections ─────────────────────────────────────────────────────────

def test_extract_sections_colon_format():
    from analysis import _extract_sections
    content = "Challenge: Reduce costs.\nApproach: Use ML.\nResults: 20% savings."
    s = _extract_sections(content)
    assert s["challenge"] == "Reduce costs."
    assert s["approach"] == "Use ML."
    assert s["results"] == "20% savings."


def test_extract_sections_newline_format():
    from analysis import _extract_sections
    content = "Challenge\nReduce costs.\n\nApproach\nUse ML.\n\nResults\n20% savings."
    s = _extract_sections(content)
    assert "challenge" in s
    assert "approach" in s
    assert "results" in s


def test_extract_sections_missing_section():
    from analysis import _extract_sections
    s = _extract_sections("Challenge: Hard problem.\nApproach: Good method.")
    assert "challenge" in s
    assert "approach" in s
    assert "results" not in s


def test_extract_sections_empty_string():
    from analysis import _extract_sections
    assert _extract_sections("") == {}


def test_extract_sections_no_headers():
    from analysis import _extract_sections
    assert _extract_sections("A project about demand planning with no section labels.") == {}


def test_extract_sections_outcomes_alias():
    from analysis import _extract_sections
    s = _extract_sections("Challenge: Hard problem.\nOutcomes: Good things happened.")
    assert s.get("results") == "Good things happened."


def test_extract_sections_case_insensitive():
    from analysis import _extract_sections
    s = _extract_sections("CHALLENGE: Hard problem.\nAPPROACH: Good method.")
    assert "challenge" in s
    assert "approach" in s


def test_extract_sections_first_occurrence_wins():
    from analysis import _extract_sections
    s = _extract_sections("Challenge: First.\nApproach: Middle.\nResults: End.\nChallenge: Second.")
    assert s["challenge"] == "First."


# ── match_case_studies ────────────────────────────────────────────────────────

def test_match_case_studies_empty_library():
    from analysis import match_case_studies
    assert match_case_studies("We need to optimise routes.", []) == []


def test_match_case_studies_returns_results():
    with patch("analysis._call_claude", return_value=_MOCK_CLAUDE_RESPONSE):
        from analysis import match_case_studies
        results = match_case_studies("We need to optimise routes.", SAMPLE_CASE_STUDIES)
    assert len(results) >= 1
    assert len(results) <= 5


def test_match_case_studies_sorted_by_score():
    with patch("analysis._call_claude", return_value=_MOCK_CLAUDE_RESPONSE):
        from analysis import match_case_studies
        results = match_case_studies("We need to optimise routes.", SAMPLE_CASE_STUDIES)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_match_case_studies_result_has_required_keys():
    with patch("analysis._call_claude", return_value=_MOCK_CLAUDE_RESPONSE):
        from analysis import match_case_studies
        results = match_case_studies("We need to optimise routes.", SAMPLE_CASE_STUDIES)
    for r in results:
        for key in ("id", "title", "industry_full", "engagement_type", "has_video", "score", "explanation"):
            assert key in r


def test_match_case_studies_merges_library_metadata():
    with patch("analysis._call_claude", return_value=_MOCK_CLAUDE_RESPONSE):
        from analysis import match_case_studies
        results = match_case_studies("We need to optimise routes.", SAMPLE_CASE_STUDIES)
    first = next(r for r in results if r["id"] == 1)
    assert first["title"] == "Route Optimisation"
    assert first["industry_full"] == "Logistics"
    assert first["engagement_type"] == "Machine Learning"
    assert first["has_video"] == 0


def test_match_case_studies_sends_sections_not_raw_content():
    captured = {}

    def capture(system, user, **kwargs):
        captured["user"] = user
        return _MOCK_CLAUDE_RESPONSE

    with patch("analysis._call_claude", side_effect=capture):
        from analysis import match_case_studies
        match_case_studies("rfp text", SAMPLE_CASE_STUDIES)

    payload = captured["user"]
    assert '"challenge"' in payload
    assert "slide_content" not in payload


def test_match_case_studies_fallback_to_raw_when_no_sections():
    unstructured = [
        {
            "id": 3,
            "title": "Unstructured Project",
            "industry_full": "Retail",
            "engagement_type": "Data & Analytics",
            "has_video": 0,
            "slide_content": "A project about demand planning with no structured sections.",
        }
    ]
    mock = {
        "text": '[{"id": 3, "score": 60, "explanation": "Relevant."}]',
        "input_tokens": 100,
        "output_tokens": 30,
        "truncated": False,
    }
    captured = {}

    def capture(system, user, **kwargs):
        captured["user"] = user
        return mock

    with patch("analysis._call_claude", side_effect=capture):
        from analysis import match_case_studies
        results = match_case_studies("rfp text", unstructured)

    assert results[0]["id"] == 3
    assert '"content"' in captured["user"]
    assert "slide_content" not in captured["user"]
