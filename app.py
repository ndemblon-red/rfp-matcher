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

if not os.getenv("OPENAI_API_KEY"):
    app.logger.warning(
        "OPENAI_API_KEY is not set — embedding generation and similarity search will be unavailable. "
        "Add it to .env to enable the two-step matching pipeline."
    )


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
    engagement_types = get_distinct("engagement_type")
    last_sync = get_last_sync()
    count = get_case_study_count()
    return render_template(
        "library.html",
        case_studies=case_studies,
        industries=industries,
        engagement_types=engagement_types,
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


@app.route("/sync/embed", methods=["POST"])
def sync_embed():
    from analysis import store_embeddings
    try:
        stats = store_embeddings()
        return stats
    except RuntimeError as e:
        app.logger.warning("store_embeddings failed: %s", e)
        return {"error": str(e)}, 400
    except Exception as e:
        app.logger.error("store_embeddings failed: %s", e, exc_info=True)
        return {"error": f"Embedding generation failed: {e}"}, 500


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

    from analysis import generate_brief
    try:
        brief = generate_brief(text)
    except Exception as e:
        app.logger.warning("generate_brief failed for %s: %s", file.filename, e)
        brief = None

    session["rfp_stem"] = stem
    session["rfp_filename"] = file.filename
    session["rfp_word_count"] = len(text.split())
    session["match_brief"] = brief
    return redirect(url_for("match_preview"))


@app.route("/match/preview")
def match_preview():
    from flask import session

    stem = session.get("rfp_stem")
    if not stem:
        flash("No RFP loaded. Please upload a document.", "warning")
        return redirect(url_for("match"))

    filename = session.get("rfp_filename", "Unknown file")
    word_count = session.get("rfp_word_count", 0)
    brief = session.get("match_brief")
    return render_template("match_preview.html", filename=filename, brief=brief, word_count=word_count)


@app.route("/match/analyze", methods=["POST"])
def match_analyze():
    from flask import session
    from analysis import match_case_studies
    from db import get_case_studies_for_scoring

    keywords = request.form.get("keywords", "").strip()
    if keywords:
        rfp_text = keywords
        from analysis import generate_brief
        try:
            brief = generate_brief(rfp_text)
        except Exception as e:
            app.logger.warning("generate_brief failed for keyword input: %s", e)
            brief = None
        session["match_brief"] = brief
    else:
        stem = session.get("rfp_stem")
        if not stem:
            flash("No RFP text found. Please upload a document or describe your need.", "warning")
            return redirect(url_for("match"))
        text_path = os.path.join(app.config["UPLOAD_FOLDER"], stem + ".txt")
        if not os.path.exists(text_path):
            flash("Extracted text not found. Please re-upload.", "error")
            return redirect(url_for("match"))
        with open(text_path, encoding="utf-8") as f:
            rfp_text = f.read()

    case_studies = get_case_studies_for_scoring()
    brief = session.get("match_brief")
    capabilities = brief.get("capabilities_needed", []) if brief else []

    try:
        results = match_case_studies(rfp_text, case_studies, brief_capabilities=capabilities, brief=brief)
    except Exception as e:
        app.logger.error("match_case_studies failed: %s", e, exc_info=True)
        flash("Analysis failed. Please try again.", "error")
        return redirect(url_for("match"))

    session["match_results"] = results
    return redirect(url_for("match_results"))


@app.route("/match/results")
def match_results():
    from flask import session

    results = session.get("match_results")
    if results is None:
        flash("No results to show. Run an analysis first.", "warning")
        return redirect(url_for("match"))
    brief = session.get("match_brief")
    problem_type = session.get("match_problem_type", "")
    return render_template("match_results.html", results=results, problem_type=problem_type, brief=brief)


# ── Startup ────────────────────────────────────────────────────────────────────

with app.app_context():
    from db import init_db
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
