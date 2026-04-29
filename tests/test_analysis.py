"""Tests for analysis.py — extract_requirements and score_case_studies."""
from unittest.mock import patch


# ── Shared test data ──────────────────────────────────────────────────────────

SAMPLE_REQUIREMENTS = {
    "off_topic": False,
    "industry_signals": ["logistics", "supply chain"],
    "problem_type": "route optimisation for a delivery fleet",
    "capabilities_needed": ["predictive analytics", "machine learning"],
    "keywords": ["logistics", "delivery", "route", "fleet", "efficiency", "cost"],
}

SAMPLE_CASE_STUDIES = [
    {
        "id": 1,
        "title": "Logistics Route Optimisation",
        "industry_full": "Logistics & Supply Chain",
        "ai_type": "Predictive Analytics",
        "has_video": 0,
        "slide_content": (
            "We helped a major logistics company optimise delivery routes using machine learning. "
            "Reduced fleet costs by 20%. Improved efficiency across 500 delivery vehicles."
        ),
    },
    {
        "id": 2,
        "title": "Healthcare AI Diagnosis",
        "industry_full": "Healthcare",
        "ai_type": "Computer Vision",
        "has_video": 1,
        "slide_content": "AI-powered diagnostic tool for radiology departments. Reduced diagnosis time by 40%.",
    },
    {
        "id": 3,
        "title": "Retail Demand Forecasting",
        "industry_full": "Retail",
        "ai_type": "Predictive Analytics",
        "has_video": 0,
        "slide_content": "Demand forecasting model for a leading retailer. Improved inventory management and reduced waste.",
    },
]


# ── extract_requirements ──────────────────────────────────────────────────────

def test_extract_requirements_returns_expected_keys():
    mock_response = {
        "text": (
            '{"off_topic": false, "industry_signals": ["logistics"], '
            '"problem_type": "fleet optimisation", '
            '"capabilities_needed": ["machine learning"], '
            '"keywords": ["route", "fleet", "delivery"]}'
        ),
        "input_tokens": 100,
        "output_tokens": 50,
        "truncated": False,
    }
    with patch("analysis._call_claude", return_value=mock_response):
        from analysis import extract_requirements
        result = extract_requirements("We need to optimise our delivery routes.")

    assert result["off_topic"] is False
    for key in ("industry_signals", "problem_type", "capabilities_needed", "keywords"):
        assert key in result
    assert isinstance(result["keywords"], list)


def test_extract_requirements_flags_off_topic():
    mock_response = {
        "text": '{"off_topic": true, "off_topic_reason": "Input is a joke, not a business problem."}',
        "input_tokens": 50,
        "output_tokens": 20,
        "truncated": False,
    }
    with patch("analysis._call_claude", return_value=mock_response):
        from analysis import extract_requirements
        result = extract_requirements("Why did the chicken cross the road?")

    assert result["off_topic"] is True
    assert "off_topic_reason" in result


def test_extract_requirements_handles_markdown_fences():
    mock_response = {
        "text": (
            '```json\n{"off_topic": false, "industry_signals": [], '
            '"problem_type": "test", "capabilities_needed": [], "keywords": []}\n```'
        ),
        "input_tokens": 50,
        "output_tokens": 30,
        "truncated": False,
    }
    with patch("analysis._call_claude", return_value=mock_response):
        from analysis import extract_requirements
        result = extract_requirements("We need a digital transformation strategy.")

    assert result["off_topic"] is False


# ── score_case_studies ────────────────────────────────────────────────────────

def test_score_case_studies_ranks_by_score():
    from analysis import score_case_studies
    results = score_case_studies(SAMPLE_REQUIREMENTS, SAMPLE_CASE_STUDIES)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_score_case_studies_best_match_is_logistics():
    from analysis import score_case_studies
    results = score_case_studies(SAMPLE_REQUIREMENTS, SAMPLE_CASE_STUDIES)
    # Logistics case study has both industry signal and keyword overlap — must rank first
    assert results[0]["id"] == 1


def test_score_case_studies_returns_top_n():
    from analysis import score_case_studies
    results = score_case_studies(SAMPLE_REQUIREMENTS, SAMPLE_CASE_STUDIES, top_n=2)
    assert len(results) <= 2


def test_score_case_studies_result_has_required_keys():
    from analysis import score_case_studies
    results = score_case_studies(SAMPLE_REQUIREMENTS, SAMPLE_CASE_STUDIES)
    for r in results:
        for key in ("id", "title", "industry_full", "ai_type", "has_video", "score", "explanation"):
            assert key in r
        assert isinstance(r["score"], float)
        assert isinstance(r["explanation"], str)
        assert len(r["explanation"]) > 0


def test_score_case_studies_empty_library():
    from analysis import score_case_studies
    results = score_case_studies(SAMPLE_REQUIREMENTS, [])
    assert results == []


def test_score_case_studies_empty_requirements():
    from analysis import score_case_studies
    results = score_case_studies(
        {"off_topic": False, "industry_signals": [], "capabilities_needed": [], "keywords": []},
        SAMPLE_CASE_STUDIES,
    )
    # All scores will be 0 — function should still return list without crashing
    assert isinstance(results, list)
    for r in results:
        assert r["score"] == 0.0
