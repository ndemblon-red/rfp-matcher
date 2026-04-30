"""Smoke tests: every route returns 200 or 302, never 500."""
from unittest.mock import patch

_MOCK_RESULTS = [
    {
        "id": 1,
        "title": "Logistics Case Study",
        "industry_full": "Logistics",
        "engagement_type": "Machine Learning",
        "has_video": 0,
        "score": 80,
        "explanation": "Strong match on route optimisation and fleet cost reduction.",
    }
]


def test_root_redirects_to_library(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert b"/library" in resp.data


def test_library_loads(client):
    resp = client.get("/library")
    assert resp.status_code == 200
    assert b"Library" in resp.data


def test_library_detail_404_on_missing(client):
    resp = client.get("/library/99999")
    assert resp.status_code == 302  # flashes error, redirects to library


def test_sync_page_loads(client):
    resp = client.get("/sync")
    assert resp.status_code == 200
    assert b"Sync" in resp.data


def test_match_page_loads(client):
    resp = client.get("/match")
    assert resp.status_code == 200
    assert b"RFP" in resp.data


def test_404_returns_error_page(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert b"not found" in resp.data.lower()


def test_match_analyze_with_keywords_redirects_to_results(client):
    with patch("analysis.match_case_studies", return_value=_MOCK_RESULTS):
        resp = client.post("/match/analyze", data={"keywords": "AI strategy for a logistics company"})
    assert resp.status_code == 302
    assert b"/match/results" in resp.data


def test_match_analyze_empty_results_redirects_to_match(client):
    with patch("analysis.match_case_studies", return_value=[]):
        resp = client.post("/match/analyze", data={"keywords": "AI strategy for a logistics company"})
    assert resp.status_code == 302
    assert b"/match/results" not in resp.data


def test_match_results_loads_with_session(client):
    with client.session_transaction() as sess:
        sess["match_results"] = _MOCK_RESULTS
        sess["match_problem_type"] = "fleet optimisation"
    resp = client.get("/match/results")
    assert resp.status_code == 200
    assert b"Match Results" in resp.data


def test_match_results_redirects_without_session(client):
    resp = client.get("/match/results")
    assert resp.status_code == 302
    assert b"/match" in resp.data
