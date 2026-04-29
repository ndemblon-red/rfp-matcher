# Logging & Observability Reference

This file contains logging setup and conventions for ADL Catalyst applications. Read this file when building Slice 1 (to set up app-wide logging) and refer back when adding logging to new features.

For enterprise PoCs and internal tools, the goal is simple: when something goes wrong, you can find out what happened from the logs without attaching a debugger. These patterns give you that with minimal overhead.

## Table of Contents

1. [App-Wide Logging Setup](#app-wide-logging-setup)
2. [Request Logging](#request-logging)
3. [What to Log (and What Not To)](#what-to-log-and-what-not-to)
4. [AI Call Logging](#ai-call-logging)
5. [Error Logging](#error-logging)
6. [Log Format Reference](#log-format-reference)

---

## App-Wide Logging Setup

Configure logging once in `app.py` before anything else runs. This sets up structured, timestamped output to both console and file:

```python
import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(app):
    """Configure app-wide logging. Call once at startup."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — always active
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    # File handler — rotates at 5MB, keeps 3 backups
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)

    # Apply to root logger so all modules inherit it
    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    app.logger.info(f"Logging initialised at {log_level} level")
```

Call it in `app.py` right after creating the Flask app:

```python
app = Flask(__name__)
setup_logging(app)
```

Add `LOG_LEVEL` to `.env.example`:

```
# Logging — DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
```

Add `logs/` to `.gitignore`.

### Per-module loggers

Every Python module should create its own logger at the top of the file. This makes it easy to filter logs by source:

```python
import logging
logger = logging.getLogger(__name__)
```

The `ai-patterns.md` reference already does this in `analysis.py`. Follow the same pattern in `db.py`, `extraction.py`, `report.py`, and any blueprint modules.

---

## Request Logging

Log every request with its method, path, status code, and duration. Use a `before_request` / `after_request` pair in `app.py`:

```python
import time

@app.before_request
def log_request_start():
    from flask import g
    g.request_start = time.time()

@app.after_request
def log_request_end(response):
    from flask import g, request
    duration_ms = (time.time() - getattr(g, "request_start", time.time())) * 1000
    # Skip static files to reduce noise
    if not request.path.startswith("/static"):
        app.logger.info(
            "%s %s %s %.0fms [user:%s]",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            getattr(current_user, "username", "anon"),
        )
    return response
```

This produces log lines like:

```
[2025-06-15 14:32:01] INFO app: GET /dashboard 200 45ms [user:alice]
[2025-06-15 14:32:03] INFO app: POST /things/new 302 120ms [user:alice]
[2025-06-15 14:32:05] INFO app: GET /api/analyse/7/stream 200 3200ms [user:bob]
```

The duration is especially useful for spotting slow AI calls and database queries.

---

## What to Log (and What Not To)

### Do log

- Route hits with duration (handled by request logging above)
- AI API calls: model, token counts, duration, whether the response was truncated
- Database errors and slow queries (> 1 second)
- Authentication events: login success, login failure (with username, without password), logout
- Background task start/completion
- Configuration loaded at startup (which .env values are set, without revealing their values)

### Do NOT log

- Passwords, API keys, or session tokens — ever
- Full request bodies containing user data (log a summary or record ID instead)
- Full AI prompts or responses in production (too large, may contain sensitive user data) — log at DEBUG level only
- Health check or static asset requests (too noisy)

### Auth event logging

Add these to your login/logout routes:

```python
logger.info("Login success: user=%s ip=%s", username, request.remote_addr)
logger.warning("Login failed: user=%s ip=%s", username, request.remote_addr)
logger.info("Logout: user=%s", current_user.username)
```

Log failed logins at WARNING level so they stand out when scanning for brute-force attempts.

---

## AI Call Logging

The `_call_claude` function in `ai-patterns.md` already returns token counts. Log these after every AI call to track costs and performance:

```python
import time

def ai_analyse_thing(thing_data, agent_name="AI"):
    start = time.time()
    result = _call_claude(system=system, user=user, max_tokens=16384)
    duration = time.time() - start

    logger.info(
        "AI call: func=%s tokens_in=%d tokens_out=%d truncated=%s duration=%.1fs",
        "analyse_thing",
        result["input_tokens"],
        result["output_tokens"],
        result["truncated"],
        duration,
    )

    return _safe_parse_json(result["text"], "analyse_thing")
```

This produces:

```
[2025-06-15 14:32:05] INFO analysis: AI call: func=analyse_thing tokens_in=2340 tokens_out=890 truncated=False duration=3.2s
```

Over time these logs let you answer: which AI calls are slowest? Which use the most tokens? Are any consistently truncating?

---

## Error Logging

Register a global error handler in `app.py` to catch unhandled exceptions:

```python
@app.errorhandler(Exception)
def handle_exception(e):
    # Let HTTP errors (404, 403, etc.) pass through normally
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e

    app.logger.error("Unhandled exception on %s %s", request.method, request.path, exc_info=True)
    return render_template("error.html", error="An unexpected error occurred."), 500
```

The `exc_info=True` parameter includes the full traceback in the log, which is essential for debugging without a debugger attached.

For expected errors (validation failures, missing records), log at WARNING and return a user-friendly message rather than a 500.

---

## Log Format Reference

The standard format produces lines like:

```
[TIMESTAMP] LEVEL MODULE: MESSAGE
```

Quick reference for log levels:

| Level | Use for |
|-------|---------|
| DEBUG | AI prompts/responses (dev only), SQL queries, variable dumps |
| INFO | Request hits, AI calls, login events, startup messages |
| WARNING | Failed logins, truncated AI responses, slow queries, deprecated usage |
| ERROR | Unhandled exceptions, database connection failures, AI API errors |

Set `LOG_LEVEL=DEBUG` during development, `LOG_LEVEL=INFO` in production. Never run production at DEBUG — it's too verbose and may leak sensitive data.
