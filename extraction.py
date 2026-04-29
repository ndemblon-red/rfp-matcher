"""RFP text extraction: PDF via pdfplumber, DOCX via python-docx."""
import os
import uuid
import logging
import pdfplumber
from docx import Document

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(file_path)
    if ext == ".docx":
        return _extract_docx(file_path)
    raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(path: str) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    return "\n\n".join(pages)


def _extract_docx(path: str) -> str:
    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def save_upload(file_storage, upload_folder: str) -> tuple[str, str]:
    """Save an uploaded FileStorage; return (uuid_stem, saved_path)."""
    ext = os.path.splitext(file_storage.filename)[1].lower()
    stem = str(uuid.uuid4())
    saved_path = os.path.join(upload_folder, stem + ext)
    file_storage.save(saved_path)
    logger.info("Saved upload: %s", saved_path)
    return stem, saved_path
