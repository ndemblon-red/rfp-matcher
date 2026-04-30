"""Tests for extraction.py helpers and the upload/preview routes."""
import io
import os
import pytest
from unittest.mock import patch, MagicMock


# ── Pure extraction helpers ───────────────────────────────────────────────────

def test_extract_text_rejects_unknown_extension(tmp_path):
    from extraction import extract_text
    fake = tmp_path / "doc.xyz"
    fake.write_bytes(b"data")
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(str(fake))


def test_extract_pdf_returns_text(tmp_path):
    from extraction import _extract_pdf
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"dummy")  # pdfplumber will be mocked

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Page one text."
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("extraction.pdfplumber.open", return_value=mock_pdf):
        result = _extract_pdf(str(fake_pdf))

    assert result == "Page one text."


def test_extract_pdf_skips_empty_pages(tmp_path):
    from extraction import _extract_pdf
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"dummy")

    p1 = MagicMock()
    p1.extract_text.return_value = "Hello"
    p2 = MagicMock()
    p2.extract_text.return_value = None  # image-only page
    p3 = MagicMock()
    p3.extract_text.return_value = "World"
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [p1, p2, p3]

    with patch("extraction.pdfplumber.open", return_value=mock_pdf):
        result = _extract_pdf(str(fake_pdf))

    assert "Hello" in result
    assert "World" in result


def test_extract_docx_returns_text(tmp_path):
    from extraction import _extract_docx
    fake_docx = tmp_path / "doc.docx"
    fake_docx.write_bytes(b"dummy")

    p1 = MagicMock()
    p1.text = "Paragraph one"
    p2 = MagicMock()
    p2.text = ""  # blank paragraph — should be skipped
    p3 = MagicMock()
    p3.text = "Paragraph three"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [p1, p2, p3]

    with patch("extraction.Document", return_value=mock_doc):
        result = _extract_docx(str(fake_docx))

    assert "Paragraph one" in result
    assert "Paragraph three" in result
    assert result.count("\n\n") == 1  # one separator between two non-empty paras


def test_save_upload_creates_file(tmp_path):
    from extraction import save_upload
    file_storage = MagicMock()
    file_storage.filename = "rfp_document.pdf"
    file_storage.save = MagicMock()

    stem, path = save_upload(file_storage, str(tmp_path))

    assert path.endswith(".pdf")
    assert stem in path
    file_storage.save.assert_called_once_with(path)


# ── Upload route ──────────────────────────────────────────────────────────────

def test_upload_route_rejects_wrong_extension(client):
    data = {"file": (io.BytesIO(b"data"), "document.txt")}
    resp = client.post("/match/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302
    assert b"/match" in resp.data


def test_upload_route_rejects_empty(client):
    resp = client.post("/match/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 302


def test_upload_route_success_pdf(client, tmp_path):
    extracted = "This is the RFP content about digital transformation."
    mock_brief = {
        "objective": "Digital transformation.",
        "challenges": ["Legacy systems"],
        "capabilities_needed": ["change management"],
        "context": {"industry": "", "scale": "", "constraints": ""},
    }

    with patch("extraction.save_upload", return_value=("abc123", str(tmp_path / "abc123.pdf"))), \
         patch("extraction.extract_text", return_value=extracted), \
         patch("analysis.generate_brief", return_value=mock_brief):
        data = {"file": (io.BytesIO(b"%PDF-1.4"), "rfp.pdf")}
        resp = client.post("/match/upload", data=data, content_type="multipart/form-data",
                           follow_redirects=False)

    assert resp.status_code == 302
    assert b"/match/preview" in resp.data


def test_preview_route_with_session(client):
    with client.session_transaction() as sess:
        sess["rfp_stem"] = "abc123"
        sess["rfp_filename"] = "my_rfp.pdf"
        sess["rfp_word_count"] = 200
        sess["match_brief"] = {
            "objective": "Optimise logistics fleet routes.",
            "challenges": ["High fuel costs"],
            "capabilities_needed": ["route optimisation"],
            "context": {"industry": "Logistics", "scale": "", "constraints": ""},
        }

    resp = client.get("/match/preview")
    assert resp.status_code == 200
    assert b"my_rfp.pdf" in resp.data
    assert b"RFP Brief" in resp.data


def test_preview_route_no_session_redirects(client):
    resp = client.get("/match/preview", follow_redirects=False)
    assert resp.status_code == 302
    assert b"/match" in resp.data
