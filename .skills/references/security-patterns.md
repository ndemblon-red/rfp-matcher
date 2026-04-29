# Security Patterns Reference

This file contains security guidance for ADL Catalyst applications. Read this file when setting up authentication, handling user input, configuring sessions, or building any route that accepts data from users.

These patterns are calibrated for enterprise PoCs and internal tools with a few hundred users. They are not a substitute for a full security audit before public deployment, but they close the most common gaps.

## Table of Contents

1. [Authentication Setup](#authentication-setup)
2. [Session Configuration](#session-configuration)
3. [CSRF Protection](#csrf-protection)
4. [Input Handling](#input-handling)
5. [File Upload Safety](#file-upload-safety)
6. [Security Headers](#security-headers)
7. [Rate Limiting](#rate-limiting)
8. [Secrets Management Checklist](#secrets-management-checklist)

---

## Authentication Setup

Use Flask-Login for session management and bcrypt for password hashing. Never store plaintext passwords.

```python
from flask import Flask
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import bcrypt

app = Flask(__name__)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, id, username, role="user"):
        self.id = id
        self.username = username
        self.role = role


@login_manager.user_loader
def load_user(user_id):
    row = get_user_by_id(user_id)  # from db.py
    if row:
        return User(row["id"], row["username"], row.get("role", "user"))
    return None
```

### Password hashing

```python
def hash_password(plaintext):
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(plaintext, hashed):
    return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
```

### Login route

```python
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user_row = get_user_by_username(username)  # from db.py
        if user_row and check_password(password, user_row["password_hash"]):
            login_user(User(user_row["id"], user_row["username"], user_row.get("role", "user")))
            next_page = request.args.get("next")
            # Prevent open redirect — only allow relative paths
            if next_page and not next_page.startswith("/"):
                next_page = None
            return redirect(next_page or url_for("dashboard"))

        flash("Invalid username or password.", "error")
    return render_template("login.html")
```

Key points:
- The open-redirect check on `next` is important — without it, an attacker can craft a login URL that redirects to a malicious site after successful login.
- Never reveal whether the username or password was wrong. Always use a generic message.
- Protect all routes except login and static assets with `@login_required`.

### Role-based access

For admin-only routes, create a decorator:

```python
from functools import wraps
from flask import abort

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated

# Usage:
@app.route("/admin/users")
@admin_required
def admin_users():
    ...
```

---

## Session Configuration

Configure Flask sessions to be secure by default. Set these in `app.py` after creating the Flask app:

```python
import os
from datetime import timedelta

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True    # JS cannot read the session cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # Prevents CSRF via cross-site GET
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"  # HTTPS-only in prod
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)  # Auto-logout after 8 hours
```

Set `SESSION_COOKIE_SECURE = True` only when serving over HTTPS (i.e. production). During local development over HTTP, leave it `False` or the cookie won't be sent.

---

## CSRF Protection

Use Flask-WTF's CSRFProtect for blanket CSRF protection on all POST/PUT/DELETE requests:

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)
```

In every form template, include the CSRF token:

```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <!-- form fields -->
</form>
```

For AJAX/fetch calls that use POST, include the token in a header:

```javascript
// Read the token from a meta tag in base.html
const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

fetch('/api/endpoint', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
    },
    body: JSON.stringify(data)
});
```

Add the meta tag in `base.html`:

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
```

If you have specific API endpoints that are called by external services (webhooks, etc.), exempt them explicitly rather than disabling CSRF globally:

```python
@csrf.exempt
@app.route("/webhook/external", methods=["POST"])
def external_webhook():
    ...
```

---

## Input Handling

### General principle

Never trust user input. Validate, constrain, and sanitise on the server side even if there is client-side validation.

### Form data

```python
# Always .strip() string inputs and enforce length limits
name = request.form.get("name", "").strip()[:200]

# Validate expected types
try:
    score = int(request.form.get("score", 0))
    score = max(0, min(100, score))  # Clamp to valid range
except (ValueError, TypeError):
    flash("Invalid score value.", "error")
    return redirect(request.referrer)
```

### SQL injection

Always use parameterised queries. This is covered in `references/db-patterns.md` but is worth restating: never construct SQL with f-strings or string concatenation.

```python
# CORRECT — parameterised
cur.execute("SELECT * FROM users WHERE username = %s", (username,))

# WRONG — injectable
cur.execute(f"SELECT * FROM users WHERE username = '{username}'")
```

### Jinja auto-escaping

Jinja2 auto-escapes HTML by default, which prevents XSS in most cases. Be careful with the `| safe` filter — only use it on content you control, never on user-supplied data:

```html
<!-- Safe: auto-escaped -->
<p>{{ user_comment }}</p>

<!-- Dangerous: only use | safe on trusted content -->
<div>{{ trusted_html_from_ai | safe }}</div>
```

---

## File Upload Safety

When accepting file uploads, validate file types and enforce size limits:

```python
import os
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "csv", "xlsx"}
MAX_UPLOAD_SIZE_MB = 25

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/upload", methods=["POST"])
@login_required
def upload_file():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(request.referrer)

    if not allowed_file(file.filename):
        flash(f"File type not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}", "error")
        return redirect(request.referrer)

    # secure_filename strips path traversal characters
    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(save_path)
    ...
```

Key points:
- `secure_filename()` prevents path traversal attacks (e.g. `../../etc/passwd`).
- `MAX_CONTENT_LENGTH` causes Flask to reject oversized uploads with a 413 before buffering the whole file.
- Check the extension server-side even if the form restricts it client-side.

---

## Security Headers

Add basic security headers to every response using an `after_request` hook:

```python
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP: adjust script-src if you use inline scripts or external CDNs
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response
```

The CSP above allows inline scripts and styles (needed for the Jinja + inline CSS architecture) while blocking external script injection. Adjust `connect-src` if you make calls to external APIs from the browser.

---

## Rate Limiting

For login endpoints, add basic rate limiting to prevent brute-force attacks. Flask-Limiter is a lightweight option:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, default_limits=[])

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    ...
```

If you don't want the Flask-Limiter dependency, a minimal in-memory approach works for single-process PoCs:

```python
from collections import defaultdict
import time

_login_attempts = defaultdict(list)

def check_rate_limit(ip, max_attempts=10, window_seconds=60):
    """Return True if the IP is within limits, False if rate-limited."""
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window_seconds]
    if len(_login_attempts[ip]) >= max_attempts:
        return False
    _login_attempts[ip].append(now)
    return True
```

Apply it at the top of the login POST handler:

```python
if request.method == "POST":
    if not check_rate_limit(request.remote_addr):
        flash("Too many login attempts. Please wait a minute.", "error")
        return render_template("login.html"), 429
    ...
```

---

## Secrets Management Checklist

Before deploying or sharing any application code:

- [ ] `.env` is listed in `.gitignore`
- [ ] `.env.example` exists with placeholder values (never real secrets)
- [ ] `SECRET_KEY` is a random string of at least 32 characters (use `python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] `DEFAULT_ADMIN_PASSWORD` is changed from the default on first login, or is generated randomly at init
- [ ] No API keys, passwords, or connection strings appear in any `.py` or `.html` file
- [ ] Database password is not `postgres` or blank in any non-local environment
