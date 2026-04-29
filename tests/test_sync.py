"""Tests for sync helpers and the /sync/run route."""
import json
import pytest
from unittest.mock import patch

from sync import _dedupe_video_variants


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row(title_hint, slide_num=1, is_video_variant=False, slide_content=""):
    return {
        "title_hint":       title_hint,
        "slide_num":        slide_num,
        "is_video_variant": is_video_variant,
        "slide_content":    slide_content,
    }


_DEFAULT_META = {
    "industry_full": "Financial Services",
    "ai_type":       "Generative AI",
}


def _slide(title_hint="Test Slide", slide_num=1, slide_content="content", has_video=False):
    return {
        "title_hint":    title_hint,
        "slide_num":     slide_num,
        "slide_content": slide_content,
        "has_video":     has_video,
    }


def _run(slides, meta=None, upsert_return="added", hash_exists=False):
    """Run run_sync with all external calls mocked; return (result, mock_infer, mock_upsert)."""
    if meta is None:
        meta = _DEFAULT_META
    # When hash_exists, return a record whose slide_num matches the first slide so no
    # position update is triggered in the default unchanged-slide test cases.
    first_slide_num = slides[0]["slide_num"] if slides else 1
    existing_record = {"id": 1, "slide_num": first_slide_num} if hash_exists else None
    from sync import run_sync
    with patch("sync.parse_pptx",              return_value=[]), \
         patch("sync._dedupe_video_variants",   return_value=slides), \
         patch("sync.get_case_study_by_hash",   return_value=existing_record), \
         patch("sync.update_slide_num"), \
         patch("sync.infer_metadata",           return_value=meta) as mock_infer, \
         patch("sync.upsert_case_study",        return_value=upsert_return) as mock_upsert, \
         patch("sync.log_sync_run"), \
         patch("sync.get_case_study_count",     return_value=max(1, len(slides))):
        result = run_sync()
    return result, mock_infer, mock_upsert


# ── Slide text helpers ────────────────────────────────────────────────────────

def test_section_header_slide_detected():
    from sync import _is_section_header_slide
    assert _is_section_header_slide(["Case Studies", "Selected Projects"])
    assert _is_section_header_slide(["CASE STUDIES"])

def test_content_slide_not_section_header():
    from sync import _is_section_header_slide
    assert not _is_section_header_slide(["CASE STUDIES | Alpha Project", "Challenge: cost"])
    assert not _is_section_header_slide(["Digital Transformation"])

def test_extract_heading_title():
    from sync import _extract_heading_title
    assert _extract_heading_title(["CASE STUDIES | Alpha Project"]) == "ALPHA PROJECT"
    assert _extract_heading_title(["CASE STUDIES | XXX"]) == "XXX"
    assert _extract_heading_title(["Case Studies | Predictive Maintenance"]) == "PREDICTIVE MAINTENANCE"
    assert _extract_heading_title(["Some other text"]) == ""

def test_extract_heading_title_multiline():
    from sync import _extract_heading_title
    # Only the first line after the pipe should be taken
    assert _extract_heading_title(["CASE STUDIES | Alpha Project\nSubtitle"]) == "ALPHA PROJECT"


# ── Video variant detection ───────────────────────────────────────────────────

def test_video_variant_pattern():
    from sync import _VIDEO_VARIANT
    assert _VIDEO_VARIANT.search("Version with Video")
    assert _VIDEO_VARIANT.search("version with video")
    assert _VIDEO_VARIANT.search("Download the version with video here")
    assert not _VIDEO_VARIANT.search("Challenge: reduce cost")


# ── Note label exclusion ──────────────────────────────────────────────────────

def test_note_label_pattern():
    from sync import _NOTE_LABEL
    assert _NOTE_LABEL.match("Note: internal use only")
    assert _NOTE_LABEL.match("NOTE: do not share")
    assert not _NOTE_LABEL.match("Challenge: cost reduction")
    assert not _NOTE_LABEL.match("Results: positive")


# ── Appendix pattern ──────────────────────────────────────────────────────────

def test_appendix_pattern_matches():
    from sync import _APPENDIX_RE
    assert _APPENDIX_RE.match("Appendix")
    assert _APPENDIX_RE.match("APPENDIX")
    assert _APPENDIX_RE.match("Appendix A — Details")

def test_appendix_pattern_no_match():
    from sync import _APPENDIX_RE
    assert not _APPENDIX_RE.match("Not an appendix")
    assert not _APPENDIX_RE.match("See appendix for details")


# ── Video deduplication ───────────────────────────────────────────────────────

def test_dedupe_base_gets_has_video_true():
    rows = [_row("Smart Search", 1), _row("Smart Search", 2, is_video_variant=True)]
    result = _dedupe_video_variants(rows)
    assert len(result) == 1
    assert result[0]["title_hint"] == "Smart Search"
    assert result[0]["has_video"] is True

def test_dedupe_drops_video_variant_slide():
    rows = [_row("Alpha", 1), _row("Alpha", 2, is_video_variant=True)]
    result = _dedupe_video_variants(rows)
    assert len(result) == 1
    assert result[0]["slide_num"] == 1

def test_dedupe_video_only_kept_with_has_video_true():
    rows = [_row("Bonus Engine", 3, is_video_variant=True)]
    result = _dedupe_video_variants(rows)
    assert len(result) == 1
    assert result[0]["has_video"] is True
    assert result[0]["title_hint"] == "Bonus Engine"

def test_dedupe_non_video_has_video_false():
    rows = [_row("Digital Strategy", 1), _row("Budget Optimisation", 2)]
    result = _dedupe_video_variants(rows)
    assert all(r["has_video"] is False for r in result)
    assert len(result) == 2

def test_dedupe_multiple_variants():
    rows = [
        _row("Alpha", 1),
        _row("Alpha", 2, is_video_variant=True),
        _row("Beta", 3),
        _row("Beta", 4, is_video_variant=True),
        _row("Gamma", 5),
    ]
    result = _dedupe_video_variants(rows)
    assert [r["title_hint"] for r in result] == ["Alpha", "Beta", "Gamma"]
    assert result[0]["has_video"] is True
    assert result[1]["has_video"] is True
    assert result[2]["has_video"] is False

def test_dedupe_preserves_slide_content():
    rows = [_row("Alpha", 1, slide_content="Challenge: reduce costs")]
    result = _dedupe_video_variants(rows)
    assert result[0]["slide_content"] == "Challenge: reduce costs"


# ── parse_pptx boundary check ─────────────────────────────────────────────────

def test_parse_pptx_raises_on_empty_path():
    from sync import parse_pptx
    with pytest.raises(ValueError, match="PPTX_PATH"):
        parse_pptx("")


# ── Local metadata inference ──────────────────────────────────────────────────

def test_infer_industry_from_bracket():
    from sync import _infer_industry
    assert _infer_industry("COST REDUCTION (PHARMACEUTICAL)", "") == "Healthcare & Life Sciences"
    assert _infer_industry("PRICE FORECASTING (PETROCHEMICAL)", "") == "Chemicals"
    assert _infer_industry("DEMAND FORECASTING (ENERGY)", "")       == "Energy Utilities & Resources"

def test_infer_industry_falls_back_to_slide_text():
    from sync import _infer_industry
    assert _infer_industry("DIGITAL TRANSFORMATION", "banking sector modernisation") == "Financial Services"

def test_infer_industry_bracket_takes_priority():
    from sync import _infer_industry
    # Bracket says pharmaceutical; slide text says banking — bracket wins
    assert _infer_industry("PROJECT (PHARMACEUTICAL)", "finance and banking details") == "Healthcare & Life Sciences"

def test_infer_industry_returns_none_on_no_match():
    from sync import _infer_industry
    assert _infer_industry("RANDOM PROJECT", "no relevant keywords here") is None

def test_infer_ai_type_generative():
    from sync import _infer_ai_type
    assert _infer_ai_type("GenAI solution with RAG pipeline")  == "Generative AI"
    assert _infer_ai_type("LLM-powered assistant")             == "Generative AI"
    assert _infer_ai_type("Microsoft Copilot integration")     == "Generative AI"

def test_infer_ai_type_machine_learning():
    from sync import _infer_ai_type
    assert _infer_ai_type("demand forecasting model")   == "Machine Learning"
    assert _infer_ai_type("machine learning pipeline")  == "Machine Learning"
    assert _infer_ai_type("price prediction algorithm") == "Machine Learning"

def test_infer_ai_type_computer_vision():
    from sync import _infer_ai_type
    assert _infer_ai_type("computer vision for defect detection") == "Computer Vision"
    assert _infer_ai_type("image recognition system")             == "Computer Vision"

def test_infer_ai_type_nlp():
    from sync import _infer_ai_type
    assert _infer_ai_type("NLP model for document extraction")  == "NLP"
    assert _infer_ai_type("natural language understanding")     == "NLP"
    assert _infer_ai_type("sentiment analysis of reviews")      == "NLP"

def test_infer_ai_type_data_analytics():
    from sync import _infer_ai_type
    assert _infer_ai_type("analytics dashboard for reporting")  == "Data & Analytics"
    assert _infer_ai_type("enterprise BI platform")             == "Data & Analytics"

def test_infer_ai_type_software_platform():
    from sync import _infer_ai_type
    assert _infer_ai_type("cloud migration and DevOps enablement") == "Software & Platform"
    assert _infer_ai_type("web portal development")                == "Software & Platform"

def test_infer_ai_type_strategy():
    from sync import _infer_ai_type
    assert _infer_ai_type("AI strategy and operating model design") == "Strategy"
    assert _infer_ai_type("digital roadmap and maturity assessment") == "Strategy"

def test_infer_ai_type_returns_none_on_no_match():
    from sync import _infer_ai_type
    assert _infer_ai_type("project update and status report") is None

def test_infer_metadata_returns_both_fields():
    from sync import infer_metadata
    result = infer_metadata("DRUG DISCOVERY (PHARMACEUTICAL)", "machine learning for compound screening")
    assert result["industry_full"] == "Healthcare & Life Sciences"
    assert result["ai_type"]       == "Machine Learning"

def test_infer_metadata_returns_none_for_unknown():
    from sync import infer_metadata
    result = infer_metadata("MYSTERY PROJECT", "no keywords present at all")
    assert result["industry_full"] is None
    assert result["ai_type"]       is None


# ── run_sync unit tests (all I/O mocked) ─────────────────────────────────────

def test_run_sync_infers_and_upserts():
    slide = _slide("Cost Reduction", slide_num=5)
    result, mock_infer, mock_upsert = _run([slide])

    assert result["added"] == 1
    assert result["skipped"] == 0
    mock_infer.assert_called_once()
    mock_upsert.assert_called_once()

def test_run_sync_passes_project_name_from_title_hint():
    slide = _slide("Predictive Maintenance", slide_num=7)
    result, _, mock_upsert = _run([slide])

    kw = mock_upsert.call_args_list[0].kwargs
    assert kw["title"] == "Predictive Maintenance"

def test_run_sync_passes_slide_num():
    slide = _slide("Alpha", slide_num=12)
    result, _, mock_upsert = _run([slide])

    kw = mock_upsert.call_args_list[0].kwargs
    assert kw["slide_num"] == 12

def test_run_sync_passes_has_video():
    slide = _slide("Alpha", has_video=True)
    result, _, mock_upsert = _run([slide])
    assert mock_upsert.call_args_list[0].kwargs["has_video"] == 1

def test_run_sync_has_video_false_passes_zero():
    slide = _slide("Beta", has_video=False)
    result, _, mock_upsert = _run([slide])
    assert mock_upsert.call_args_list[0].kwargs["has_video"] == 0

def test_run_sync_passes_slide_content():
    slide = _slide("Alpha", slide_content="My slide content")
    result, _, mock_upsert = _run([slide])
    assert mock_upsert.call_args_list[0].kwargs["slide_content"] == "My slide content"

def test_run_sync_passes_all_metadata_fields():
    slide = _slide("Pfizer Drug Discovery", slide_num=5)
    meta = {
        "industry_full": "Healthcare & Life Sciences",
        "ai_type":       "Machine Learning",
    }
    result, _, mock_upsert = _run([slide], meta=meta)

    kw = mock_upsert.call_args_list[0].kwargs
    assert kw["title"]         == "Pfizer Drug Discovery"
    assert kw["slide_num"]     == 5
    assert kw["industry_full"] == "Healthcare & Life Sciences"
    assert kw["ai_type"]       == "Machine Learning"

def test_run_sync_skips_slide_with_no_title():
    slide = _slide("", slide_num=3)   # empty title_hint
    result, _, mock_upsert = _run([slide])
    assert result["skipped"] == 1
    mock_upsert.assert_not_called()

def test_run_sync_counts_updated_vs_added():
    slides = [_slide("Alpha"), _slide("Beta")]
    from sync import run_sync
    with patch("sync.parse_pptx",            return_value=[]), \
         patch("sync._dedupe_video_variants", return_value=slides), \
         patch("sync.infer_metadata",         return_value=_DEFAULT_META), \
         patch("sync.upsert_case_study",      side_effect=["added", "updated"]), \
         patch("sync.log_sync_run"), \
         patch("sync.get_case_study_count",   return_value=2):
        result = run_sync()

    assert result["added"]   == 1
    assert result["updated"] == 1

def test_run_sync_returns_empty_warnings():
    result, _, _ = _run([_slide("A")])
    assert result["warnings"] == []

def test_run_sync_skips_unchanged_slide():
    slide = _slide("Alpha")
    result, mock_infer, mock_upsert = _run([slide], hash_exists=True)
    assert result["unchanged"] == 1
    assert result["added"] == 0
    mock_infer.assert_not_called()
    mock_upsert.assert_not_called()

def test_run_sync_processes_changed_slide():
    slide = _slide("Alpha")
    result, mock_infer, mock_upsert = _run([slide], hash_exists=False)
    assert result["unchanged"] == 0
    assert result["added"] == 1
    mock_infer.assert_called_once()
    mock_upsert.assert_called_once()

def test_run_sync_passes_content_hash_to_upsert():
    slide = _slide("Alpha", slide_content="Some slide content")
    result, _, mock_upsert = _run([slide], hash_exists=False)
    kw = mock_upsert.call_args_list[0].kwargs
    assert "content_hash" in kw
    assert len(kw["content_hash"]) == 12

def test_hash_content_is_deterministic():
    from sync import _hash_content
    assert _hash_content("hello") == _hash_content("hello")
    assert _hash_content("hello") != _hash_content("world")
    assert len(_hash_content("anything")) == 12


# ── Slide number shift handling ───────────────────────────────────────────────

def test_run_sync_updates_slide_num_when_slide_moves():
    slide = _slide("Alpha", slide_num=15)
    from sync import run_sync
    with patch("sync.parse_pptx",            return_value=[]), \
         patch("sync._dedupe_video_variants", return_value=[slide]), \
         patch("sync.get_case_study_by_hash", return_value={"id": 7, "slide_num": 10}), \
         patch("sync.update_slide_num")      as mock_update, \
         patch("sync.infer_metadata",         return_value=_DEFAULT_META), \
         patch("sync.upsert_case_study",      return_value="added"), \
         patch("sync.log_sync_run"), \
         patch("sync.get_case_study_count",   return_value=1):
        result = run_sync()
    assert result["unchanged"] == 1
    assert result["added"] == 0
    mock_update.assert_called_once_with(7, 15)

def test_run_sync_no_update_when_slide_num_unchanged():
    slide = _slide("Alpha", slide_num=10)
    from sync import run_sync
    with patch("sync.parse_pptx",            return_value=[]), \
         patch("sync._dedupe_video_variants", return_value=[slide]), \
         patch("sync.get_case_study_by_hash", return_value={"id": 7, "slide_num": 10}), \
         patch("sync.update_slide_num")      as mock_update, \
         patch("sync.infer_metadata",         return_value=_DEFAULT_META), \
         patch("sync.upsert_case_study",      return_value="added"), \
         patch("sync.log_sync_run"), \
         patch("sync.get_case_study_count",   return_value=1):
        result = run_sync()
    assert result["unchanged"] == 1
    mock_update.assert_not_called()


# ── /sync/run route ───────────────────────────────────────────────────────────

def test_sync_run_route_returns_json(client):
    mock_stats = {"added": 5, "updated": 100, "skipped": 0, "total": 105, "warnings": []}
    with patch("sync.run_sync", return_value=mock_stats):
        resp = client.post("/sync/run")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["added"] == 5
    assert data["total"] == 105

def test_sync_run_route_handles_config_error(client):
    with patch("sync.run_sync", side_effect=ValueError("PPTX_PATH is not configured")):
        resp = client.post("/sync/run")
    assert resp.status_code == 400
    assert "error" in json.loads(resp.data)

def test_sync_run_route_handles_unexpected_error(client):
    with patch("sync.run_sync", side_effect=Exception("file not found")):
        resp = client.post("/sync/run")
    assert resp.status_code == 500
    assert "error" in json.loads(resp.data)
