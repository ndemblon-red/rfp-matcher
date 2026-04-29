"""Smoke tests: every route returns 200 or 302, never 500."""


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


def test_match_keywords_post_redirects_to_preview(client):
    resp = client.post("/match/analyze", data={"keywords": "AI strategy for logistics"})
    assert resp.status_code == 302
    assert b"keywords-preview" in resp.data


def test_match_keywords_preview_loads_with_session(client):
    with client.session_transaction() as sess:
        sess["rfp_keywords"] = "AI strategy for a logistics company"
    resp = client.get("/match/keywords-preview")
    assert resp.status_code == 200
    assert b"AI strategy" in resp.data


def test_match_keywords_preview_redirects_without_session(client):
    resp = client.get("/match/keywords-preview")
    assert resp.status_code == 302
    assert b"/match" in resp.data
