"""Database CRUD tests against the test database."""
from db import (upsert_case_study, get_case_study, get_all_case_studies,
                get_case_study_count, content_hash_exists,
                get_case_study_by_hash, update_slide_num)


def test_upsert_and_read(setup_db):
    upsert_case_study(
        title="Test Project Alpha",
        slide_num=5,
        industry_full="Financial Services",
        engagement_type="Generative AI",
        slide_content="Challenge: cost reduction. Result: 20% savings.",
        challenge=None,
        approach=None,
        results=None,
    )
    titles = [cs["title"] for cs in get_all_case_studies()]
    assert "Test Project Alpha" in titles


def test_upsert_updates_existing(setup_db):
    upsert_case_study(
        title="Test Project Alpha",
        slide_num=5,
        industry_full="Financial Services",
        engagement_type="Machine Learning",   # changed
        slide_content="Updated content.",
        challenge=None,
        approach=None,
        results=None,
    )
    match = next(cs for cs in get_all_case_studies() if cs["title"] == "Test Project Alpha")
    assert match["engagement_type"] == "Machine Learning"


def test_upsert_stores_slide_num(setup_db):
    upsert_case_study(
        title="Slide Num Check Project",
        slide_num=42,
        industry_full="Financial Services",
        engagement_type="Generative AI",
        slide_content="content",
        challenge=None,
        approach=None,
        results=None,
    )
    match = next(cs for cs in get_all_case_studies() if cs["title"] == "Slide Num Check Project")
    assert match["slide_num"] == 42


def test_upsert_allows_duplicate_titles(setup_db):
    upsert_case_study(
        title="SHARED NAME",
        slide_num=201,
        industry_full=None,
        engagement_type=None,
        slide_content="first",
        challenge=None,
        approach=None,
        results=None,
    )
    upsert_case_study(
        title="SHARED NAME",
        slide_num=202,
        industry_full=None,
        engagement_type=None,
        slide_content="second",
        challenge=None,
        approach=None,
        results=None,
    )
    matches = [cs for cs in get_all_case_studies() if cs["title"] == "SHARED NAME"]
    assert len(matches) == 2


def test_upsert_sets_has_video(setup_db):
    upsert_case_study(
        title="Video Project",
        slide_num=10,
        industry_full=None,
        engagement_type=None,
        slide_content="content",
        challenge=None,
        approach=None,
        results=None,
        has_video=1,
    )
    match = next(cs for cs in get_all_case_studies() if cs["title"] == "Video Project")
    assert match["has_video"] == 1


def test_get_by_id(setup_db):
    all_cs = get_all_case_studies()
    if not all_cs:
        return
    cs = get_case_study(all_cs[0]["id"])
    assert cs is not None
    assert cs["id"] == all_cs[0]["id"]


def test_content_hash_stored_and_found(setup_db):
    upsert_case_study(
        title="Hash Test Project",
        slide_num=99,
        industry_full=None,
        engagement_type=None,
        slide_content="content",
        challenge=None,
        approach=None,
        results=None,
        content_hash="abc123def456",
    )
    assert content_hash_exists("abc123def456") is True
    assert content_hash_exists("000000000000") is False

def test_content_hash_exists_ignores_empty(setup_db):
    assert content_hash_exists("") is False
    assert content_hash_exists(None) is False

def test_get_nonexistent_returns_none(setup_db):
    assert get_case_study(999999) is None


def test_count(setup_db):
    assert get_case_study_count() >= 0


def test_get_case_study_by_hash_found(setup_db):
    upsert_case_study(
        title="Hash Lookup Project",
        slide_num=301,
        industry_full=None,
        engagement_type=None,
        slide_content="content",
        challenge=None,
        approach=None,
        results=None,
        content_hash="aabbcc001122",
    )
    result = get_case_study_by_hash("aabbcc001122")
    assert result is not None
    assert result["slide_num"] == 301


def test_get_case_study_by_hash_not_found(setup_db):
    assert get_case_study_by_hash("zzzzzzzzzzzz") is None
    assert get_case_study_by_hash("") is None
    assert get_case_study_by_hash(None) is None


def test_update_slide_num(setup_db):
    upsert_case_study(
        title="Slide Move Project",
        slide_num=401,
        industry_full=None,
        engagement_type=None,
        slide_content="content",
        challenge=None,
        approach=None,
        results=None,
    )
    record = next(cs for cs in get_all_case_studies() if cs["title"] == "Slide Move Project")
    update_slide_num(record["id"], 402)
    moved = next(cs for cs in get_all_case_studies() if cs["title"] == "Slide Move Project")
    assert moved["slide_num"] == 402
