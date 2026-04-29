import os
import time
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, redirect, url_for, request, g, render_template, flash
from dotenv import load_dotenv

load_dotenv()


def setup_logging(app):
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    os.makedirs("logs", exist_ok=True)
    fh = RotatingFileHandler("logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(log_level)
        root.addHandler(console)
        root.addHandler(fh)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    app.logger.info("Logging initialised at %s level", log_level)


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # local HTTP; set True behind HTTPS
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

setup_logging(app)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# ── Request lifecycle ──────────────────────────────────────────────────────────

@app.before_request
def _start_timer():
    g.request_start = time.time()


@app.after_request
def _log_request(response):
    if not request.path.startswith("/static"):
        ms = (time.time() - getattr(g, "request_start", time.time())) * 1000
        app.logger.info("%s %s %s %.0fms", request.method, request.path, response.status_code, ms)
    return response


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error="Page not found."), 404


@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", error="File too large. Maximum upload size is 25 MB."), 413


@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    app.logger.error("Unhandled exception on %s %s", request.method, request.path, exc_info=True)
    return render_template("error.html", error="An unexpected error occurred."), 500


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("library"))


@app.route("/library")
def library():
    from db import get_all_case_studies, get_distinct, get_last_sync, get_case_study_count
    case_studies = get_all_case_studies()
    industries = get_distinct("industry_full")
    ai_types = get_distinct("ai_type")
    last_sync = get_last_sync()
    count = get_case_study_count()
    return render_template(
        "library.html",
        case_studies=case_studies,
        industries=industries,
        ai_types=ai_types,
        last_sync=last_sync,
        count=count,
    )


@app.route("/library/<int:case_id>")
def library_detail(case_id):
    from db import get_case_study
    cs = get_case_study(case_id)
    if not cs:
        flash("Case study not found.", "error")
        return redirect(url_for("library"))
    return render_template("library_detail.html", cs=cs)


@app.route("/sync")
def sync():
    from db import get_last_sync, get_case_study_count
    last_sync = get_last_sync()
    count = get_case_study_count()
    return render_template("sync.html", last_sync=last_sync, count=count)


@app.route("/sync/run", methods=["POST"])
def sync_run():
    from sync import run_sync
    try:
        stats = run_sync()
        return stats
    except ValueError as e:
        app.logger.warning("Sync configuration error: %s", e)
        return {"error": str(e)}, 400
    except Exception as e:
        app.logger.error("Sync failed: %s", e, exc_info=True)
        return {"error": f"Sync failed: {e}"}, 500


@app.route("/match")
def match():
    return render_template("match.html")


@app.route("/match/upload", methods=["POST"])
def match_upload():
    from extraction import save_upload, extract_text
    from flask import session

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("match"))

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".pdf", ".docx"}:
        flash("Only PDF and DOCX files are accepted.", "error")
        return redirect(url_for("match"))

    stem, saved_path = save_upload(file, app.config["UPLOAD_FOLDER"])

    try:
        text = extract_text(saved_path)
    except Exception as e:
        app.logger.error("Extraction failed for %s: %s", file.filename, e, exc_info=True)
        flash("Could not extract text from the file. Please try a different document.", "error")
        return redirect(url_for("match"))

    if not text.strip():
        flash("No readable text found in the file.", "warning")
        return redirect(url_for("match"))

    text_path = os.path.join(app.config["UPLOAD_FOLDER"], stem + ".txt")
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    session["rfp_stem"] = stem
    session["rfp_filename"] = file.filename
    return redirect(url_for("match_preview"))


@app.route("/match/preview")
def match_preview():
    from flask import session

    stem = session.get("rfp_stem")
    filename = session.get("rfp_filename", "Unknown file")
    if not stem:
        flash("No RFP loaded. Please upload a document.", "warning")
        return redirect(url_for("match"))

    text_path = os.path.join(app.config["UPLOAD_FOLDER"], stem + ".txt")
    if not os.path.exists(text_path):
        flash("Extracted text not found. Please re-upload.", "error")
        return redirect(url_for("match"))

    with open(text_path, encoding="utf-8") as f:
        text = f.read()

    word_count = len(text.split())
    return render_template("match_preview.html", filename=filename, text=text, word_count=word_count)


@app.route("/match/keywords-preview")
def match_keywords_preview():
    from flask import session

    keywords = session.get("rfp_keywords")
    if not keywords:
        flash("No keywords entered. Please describe what you're looking for.", "warning")
        return redirect(url_for("match"))
    return render_template("match_keywords_preview.html", keywords=keywords)


@app.route("/match/analyze", methods=["POST"])
def match_analyze():
    from flask import session

    keywords = request.form.get("keywords", "").strip()
    if keywords:
        session["rfp_keywords"] = keywords
        return redirect(url_for("match_keywords_preview"))

    # File-based flow — implemented in Slice 5
    flash("Analysis not yet implemented.", "warning")
    return redirect(url_for("match"))


# ── Startup ────────────────────────────────────────────────────────────────────

with app.app_context():
    from db import init_db
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
