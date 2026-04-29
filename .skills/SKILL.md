---
name: adl-catalyst-fullstack
description: "Use this skill when building any web application with a database backend — from quick PoCs to enterprise internal tools. Trigger whenever the user mentions: dashboards, admin panels, internal tools, portals, trackers, management systems, reporting apps, analytics interfaces, inventory systems, compliance tools, or any request to build, prototype, or demo a multi-page web application. Also trigger for: 'build me an app', 'create a web application', 'new Flask project', 'full-stack application', 'I need a web interface for this data', 'build a PoC', 'prototype an app', 'I need something to track X', or any request that involves planning and building a modular application with forms, tables, user auth, or data entry. This skill covers architecture, design system, requirement elicitation, and a slice-based build methodology using Flask + PostgreSQL. Even if the user doesn't name a technology, if they're describing a web-based tool they want built, use this skill."
---

# ADL Catalyst Full-Stack Development Skill

## Overview

This skill defines a proven methodology for building production-quality Flask web applications through AI-augmented development. It covers architecture decisions, a complete design system, requirement elicitation, and a build process based on small, testable slices.

The core principle: **the human provides the requirement and tests; the AI generates all code**. The methodology ensures AI-generated code works reliably by constraining the architecture to patterns that produce consistent results.

### Reference Files

Read these when working on the corresponding area of the application. Don't load them all up front — read the one you need for the current slice.

| File | When to read |
|------|-------------|
| `references/design-system.md` | When building or modifying any template, styling, or UI component |
| `references/db-patterns.md` | When creating or modifying `db.py`, tables, or any database code |
| `references/ai-patterns.md` | When creating or modifying `analysis.py` or any AI/LLM integration |
| `references/security-patterns.md` | When setting up auth, handling user input, configuring sessions, or accepting uploads |
| `references/testing-patterns.md` | When building Slice 1 (test harness setup) and when adding tests to each subsequent slice |
| `references/logging-patterns.md` | When building Slice 1 (logging setup) and when adding logging to new features or AI calls |

---

## Phase 1: Architecture (Non-Negotiable)

Every application built with this skill uses the following stack. These are not suggestions — they are constraints that make AI-generated code reliable.

### Technology Menu

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend | **Flask** (Python) | Minimal framework, no magic. Each route is explicit and testable. |
| Templates | **Jinja2** (server-rendered) | No build step, no JS framework complexity. Each page is self-contained. |
| Database | **PostgreSQL** | Production-grade, JSONB for flexible AI outputs, robust migrations. |
| ORM | **None** — raw SQL via psycopg2 | AI generates cleaner SQL than ORM code. Explicit is better than implicit. |
| AI Provider | **Anthropic Claude API** | Single provider, consistent prompts, JSON-only responses. |
| Auth | **Flask-Login + bcrypt + Flask-WTF** | Session-based auth, CSRF protection. See `references/security-patterns.md` for setup. |
| Styling | **Inline CSS + CSS custom properties** | No Tailwind build step, no SCSS. Variables define the theme. |
| Fonts | **Google Fonts** (DM Sans + JetBrains Mono) | Via CDN link, no local font files. |

### File Structure

Start with this flat structure. It works well for applications up to ~10 routes:

```
project_name/
├── app.py                  # Flask app, all routes
├── db.py                   # Database connection, tables, all CRUD
├── storage.py              # JSON working session (if needed for in-progress state)
├── extraction.py           # File parsing (PDF, DOCX, TXT) if document ingestion needed
├── analysis.py             # AI/LLM calls (if AI features needed)
├── report.py               # Document generation (DOCX/PDF exports) if needed
├── requirements.txt        # Python dependencies
├── .env                    # Secrets (NEVER committed) — copy from .env.example
├── .env.example            # Template for environment variables
├── data/                   # JSON storage files, settings
├── logs/                   # Log files (gitignored, created at startup)
├── migrations/             # Destructive schema changes (if needed — see db-patterns.md)
├── uploads/                # User-uploaded files
├── static/img/             # Static assets
├── tests/
│   ├── conftest.py         # Shared fixtures (app client, test DB)
│   ├── test_smoke.py       # Route reachability tests
│   └── test_[feature].py   # One test file per feature module
└── templates/
    ├── base.html           # Master layout with theme, nav, modals
    ├── login.html          # Authentication
    ├── dashboard.html      # Home/landing page
    └── [feature].html      # One template per feature page
```

### Scaling to Blueprints

**When `app.py` exceeds ~500 lines or ~10 routes, split routes into Flask Blueprints.** This is not optional — a single file beyond this size causes context-window pressure on Claude and makes slices harder to scope.

The scaled structure moves each feature area into its own module under `routes/`:

```
project_name/
├── app.py                  # Flask app factory, registers blueprints, no route handlers
├── routes/
│   ├── __init__.py         # Empty or imports all blueprints
│   ├── auth.py             # Login, logout, registration routes
│   ├── dashboard.py        # Dashboard and home routes
│   └── [feature].py        # One file per feature module
├── db.py
├── analysis.py
├── ...                     # (other files unchanged)
└── templates/
    ├── base.html
    ├── auth/
    │   └── login.html
    ├── dashboard/
    │   └── dashboard.html
    └── [feature]/
        └── [feature].html
```

Each blueprint file follows this pattern:

```python
# routes/feature.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from db import get_things, create_thing

feature_bp = Blueprint("feature", __name__, template_folder="../templates")

@feature_bp.route("/things")
@login_required
def list_things():
    things = get_things()
    return render_template("feature/list.html", things=things)

@feature_bp.route("/things/new", methods=["GET", "POST"])
@login_required
def new_thing():
    ...
```

Register blueprints in `app.py`:

```python
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.feature import feature_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(feature_bp)
```

Templates move into subdirectories matching the blueprint name. This keeps template references predictable: `render_template("feature/list.html")`.

**When to trigger the split:** During build planning (Phase 4), count the total expected routes across all slices. If the total exceeds 10, plan the blueprint structure as part of Slice 1 (foundation). If the project starts small but grows past the threshold during build execution, introduce a dedicated refactoring slice that moves existing routes into blueprints before adding more features. This refactoring slice changes no functionality — all existing tests must still pass.

### Environment Variables (.env)

Always use a `.env` file for configuration. Never hardcode secrets.

```
# Required
SECRET_KEY=<random-string-for-sessions>
DB_HOST=localhost
DB_PORT=5432
DB_NAME=<project_name>
DB_USER=postgres
DB_PASSWORD=<password>

# Optional — AI features
ANTHROPIC_API_KEY=sk-ant-...

# Optional — branding
AGENT_NAME=<AI assistant name>
AGENT_ROLE=<AI assistant role description>
DEFAULT_ADMIN_PASSWORD=<initial admin password>

# Optional — logging
LOG_LEVEL=INFO
```

---

## Phase 2: Design System

The full design system (colour palette, typography, component CSS, layout patterns) lives in `references/design-system.md`. **Read that file before building any template.**

Summary of what it contains: light and dark theme CSS custom properties, button/card/badge/tab/accordion component styles, and the standard page layout pattern (back link → title → actions → content).

---

## Phase 3: Requirement Elicitation

When a user asks to build an application, follow this process BEFORE writing any code:

### Step 1: Understand the Domain

Ask the user:
1. **What problem does this solve?** (not "what features" — understand the business need)
2. **Who uses it?** (roles, permissions needed)
3. **What are the key workflows?** (the 3-5 things users do most)

Use your domain knowledge to fill gaps. If the user says "I need a project management tool", you know that means tasks, assignments, deadlines, statuses, and reporting — suggest these and let the user confirm or modify.

### Step 2: Define Modules

Group functionality into 2-5 modules. Each module is a coherent area of the application:
```
Module 1: [Core data entry/viewing]
Module 2: [Analysis/processing]
Module 3: [Actions/workflow]
Module 4: [Reporting/export] (if needed)
```

### Step 3: List Requirements

For each module, list specific requirements using IDs:
```
M1-01: [Description of requirement]
M1-02: [Description of requirement]
```

Present these to the user for validation before proceeding.

### Step 4: Create the Build Plan

**This is the most critical step.** Decompose the requirements into slices.

---

## Phase 4: Build Planning — Slices

### Slice Rules

Each slice MUST:
- **Be completable in a single conversation turn** — typically 200-400 lines of new/modified code
- **Add testable functionality** — the user must be able to verify it works before moving on
- **Not break existing functionality** — additive changes only (new routes, new functions, new columns)
- **Map to specific requirement IDs** — every slice has a clear scope

### Slice Structure

Each slice definition must include:
```
## Slice N: [Name]
Priority: P1/P2/P3
Requirements covered: M1-01, M1-02

### What it delivers
[1-2 sentences describing what the user can do after this slice]

### Changes
**[file].py:** [what changes]
**[file].html:** [what changes]
**db.py:** [new tables/columns if any]

### How to test
[Step-by-step verification the user can perform]
```

### Slice Sizing Guidelines

- **Small slice (1-2 files changed):** New route + template, or new AI function + route
- **Medium slice (3-4 files changed):** New DB table + CRUD + route + template
- **Large slice (4-5 files changed):** New subsystem — split into 2 slices if it exceeds ~400 lines

### Slice Ordering

1. **Foundation slices first** — core data model, basic CRUD, the primary workflow
2. **Enhancement slices next** — additional analysis, secondary workflows
3. **Polish slices last** — export, settings, admin features

### Dependency Management

Draw a dependency graph:
```
Slice 1 → Slice 2 → Slice 3
                ↓
          Slice 4 → Slice 5
```

Never build a slice that depends on an unbuilt slice.

---

## Phase 5: Build Execution

### Per-Slice Workflow

For each slice:

1. **Read the slice plan** — review what needs to change
2. **Read the relevant reference file(s)** — design-system.md for UI work, db-patterns.md for database work, ai-patterns.md for AI work
3. **Check current file state** — view the files that will be modified
4. **Implement changes** — generate code following the architecture patterns
5. **Verify compilation** — run a Python import check:
   ```python
   python -c "import app; print('Compiles')"
   ```
6. **Check brace balance** (for JS in templates):
   ```python
   awk '/block extra_js/,/endblock/' template.html | python -c "
   s=open('/dev/stdin').read(); print(f'{s.count(chr(123))} open, {s.count(chr(125))} close')
   "
   ```
7. **Update tests** — add new routes to `test_smoke.py`, add CRUD/form/AI tests as needed (see `references/testing-patterns.md`)
8. **Run the test suite** — all tests must pass before presenting to the user:
   ```bash
   pytest tests/ -v --tb=short
   ```
9. **Present files to user** — copy to outputs, present for download
10. **Wait for user testing** — do NOT proceed to the next slice until the user confirms

### Code Generation Rules

- **Never embed complex data in Jinja `<script>` blocks** — use API fetch calls instead
- **Always use `| safe` with `| tojson`** — or better, avoid inline Jinja in JS entirely
- **SSE streams need keepalive** — send `: keepalive\n\n` comments every 15 seconds
- **AI JSON responses need repair** — always use `_safe_parse_json()` with truncation recovery (see `references/ai-patterns.md`)
- **Database migrations are additive** — use `IF NOT EXISTS` for tables, `ADD COLUMN IF NOT EXISTS` for columns (see `references/db-patterns.md`)
- **All secrets from `.env`** — never hardcode API keys, passwords, or connection strings
- **Security baseline on Slice 1** — the first slice must include session config, CSRF protection, security headers, `@login_required` on all non-public routes (see `references/security-patterns.md`), and app-wide logging with request logging (see `references/logging-patterns.md`)
- **Validate all user input server-side** — strip, constrain length, check types. Never trust client-side validation alone
- **Use `secure_filename()`** for any file upload — and enforce an allowlist of extensions
- **Log every AI call** — function name, token counts, duration, and whether the response was truncated. Never log full prompts or responses at INFO level
- **Never log secrets** — no passwords, API keys, session tokens, or full request bodies containing user data
- **Split to blueprints at ~10 routes / ~500 lines in `app.py`** — see "Scaling to Blueprints" in Phase 1. If you're mid-build and hit the threshold, add a refactoring slice before the next feature slice

---

## Phase 6: Post-Build

After all slices are complete:

1. **Run the full test suite** and confirm all tests pass
2. **Generate a tarball** of the complete application (including `tests/`)
3. **Write a user manual** if the application has significant complexity
4. **Document the `.env.example`** with all required variables
5. **Verify all routes compile** and count them
6. **Offer to create a presentation** summarising the build if needed

---

## Quick Reference: When Things Go Wrong

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Unexpected token '&'` in JS | Jinja auto-escaping in `<script>` | Load data via API fetch, not inline `{{ }}` |
| `Unterminated string` JSON error | AI response truncated at max_tokens | Increase max_tokens, add `_safe_parse_json` |
| `ERR_HTTP2_PROTOCOL_ERROR` on SSE | Proxy idle timeout | Add `: keepalive\n\n` every 15s |
| Extra `}` syntax error | Brace imbalance in minified JS | Run brace-count verification |
| `NameError: name not defined` | Variable scope — using wrong reference | Check if using single-item vs collection variable |
| Template renders blank | JS error preventing execution | Check browser console, fix the first error |
| Data doesn't persist after INSERT | Missing `conn.commit()` | Add `conn.commit()` after write operations |
| `connection already closed` | Reusing a closed connection | Call `get_conn()` fresh per function call |
