# Testing Patterns Reference

This file contains testing guidance for ADL Catalyst applications. Read this file when building Slice 1 (to set up the test harness) and when adding tests alongside each subsequent slice.

The testing strategy is calibrated for enterprise PoCs: enough coverage to catch regressions and verify each slice works, without the overhead of a full CI/CD pipeline. Tests should be fast to write (the AI generates them) and fast to run (under 10 seconds for the full suite).

## Table of Contents

1. [Test Directory Structure](#test-directory-structure)
2. [Test Configuration](#test-configuration)
3. [Smoke Test — Route Reachability](#smoke-test--route-reachability)
4. [Database Tests](#database-tests)
5. [Form and Input Tests](#form-and-input-tests)
6. [AI Function Tests](#ai-function-tests)
7. [Per-Slice Testing Workflow](#per-slice-testing-workflow)
8. [Running Tests](#running-tests)

---

## Test Directory Structure

Add a `tests/` directory to the project and a `conftest.py` with shared fixtures:

```
project_name/
├── app.py
├── db.py
├── ...
├── tests/
│   ├── conftest.py         # Shared fixtures (app client, test DB, etc.)
│   ├── test_smoke.py       # Route reachability — every route returns 200 or 302
│   ├── test_db.py          # CRUD operations against a real test database
│   ├── test_auth.py        # Login, logout, protected routes, role checks
│   └── test_[feature].py   # One file per feature module as slices are built
└── requirements.txt        # Add pytest to dependencies
```

Add `pytest` to `requirements.txt`:
```
pytest>=7.0
```

---

## Test Configuration

### `tests/conftest.py`

This file creates a Flask test client and optionally a clean test database. Every test file imports fixtures from here automatically.

```python
import os
import pytest
import psycopg2

# Point at a separate test database to avoid touching real data
os.environ["DB_NAME"] = os.environ.get("DB_NAME_TEST", "testdb")
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"

from app import app as flask_app
from db import init_db, get_conn


@pytest.fixture(scope="session")
def app():
    """Create the Flask app for testing."""
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF in tests for simplicity
    flask_app.config["LOGIN_DISABLED"] = False
    return flask_app


@pytest.fixture(scope="session")
def setup_db(app):
    """Initialise tables in the test database once per test session."""
    init_db()
    yield
    # Optional: drop tables or truncate after the session
    # For PoCs, leaving the test DB intact is usually fine


@pytest.fixture()
def client(app, setup_db):
    """A Flask test client for making requests."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def auth_client(client):
    """A test client that is already logged in as the default admin user.
    Adjust the login credentials to match your seed data."""
    client.post("/login", data={
        "username": "admin",
        "password": os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin"),
    })
    yield client
```

Key points:
- `WTF_CSRF_ENABLED = False` disables CSRF checks during tests so you can POST without tokens. This is standard practice.
- `scope="session"` on the app and DB fixtures means they're created once per test run, keeping things fast.
- The `auth_client` fixture handles login once, then every test using it starts already authenticated.
- Use a separate `DB_NAME_TEST` so tests never touch the development database.

---

## Smoke Test — Route Reachability

This is the single most valuable test file. It verifies that every route in the app is reachable without 500 errors. Generate this at the end of every slice.

### `tests/test_smoke.py`

```python
"""Smoke tests: every route returns 200 or 302 (redirect to login), never 500."""


def test_public_routes(client):
    """Routes that should be accessible without login."""
    public_routes = [
        "/login",
    ]
    for route in public_routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"GET {route} returned {resp.status_code}"


def test_protected_routes_redirect_when_unauthenticated(client):
    """Protected routes should redirect to login (302), not crash (500)."""
    protected_routes = [
        "/",
        "/dashboard",
        # Add every new route here as slices are built
    ]
    for route in protected_routes:
        resp = client.get(route)
        assert resp.status_code in (200, 302), f"GET {route} returned {resp.status_code}"


def test_protected_routes_load_when_authenticated(auth_client):
    """All protected routes should return 200 when logged in."""
    protected_routes = [
        "/",
        "/dashboard",
        # Add every new route here as slices are built
    ]
    for route in protected_routes:
        resp = auth_client.get(route)
        assert resp.status_code == 200, f"GET {route} returned {resp.status_code}"
```

**As each new slice adds routes, add them to the route lists.** This is the minimal contract: no route returns a 500.

---

## Database Tests

Test CRUD functions directly against the test database. These catch schema mismatches, missing commits, and broken queries.

### `tests/test_db.py`

```python
"""Database CRUD tests — verify create, read, update, delete cycles."""
from db import create_thing, get_thing, update_thing, delete_thing  # adjust imports


def test_create_and_read(setup_db):
    thing_id = create_thing("Test Item", "test-value")
    assert thing_id is not None

    thing = get_thing(thing_id)
    assert thing is not None
    assert thing["name"] == "Test Item"


def test_update(setup_db):
    thing_id = create_thing("Before", "v1")
    update_thing(thing_id, "After", "v2")

    thing = get_thing(thing_id)
    assert thing["name"] == "After"


def test_delete(setup_db):
    thing_id = create_thing("Temporary", "tmp")
    delete_thing(thing_id)

    thing = get_thing(thing_id)
    assert thing is None


def test_get_nonexistent(setup_db):
    thing = get_thing(999999)
    assert thing is None
```

These are templates — replace `create_thing` / `get_thing` etc. with the actual CRUD functions as they're built. Each slice that adds a new table should add a corresponding test file or section.

---

## Form and Input Tests

Test that form submissions work end-to-end through the Flask routes, and that bad input is rejected.

```python
"""Test form submissions and input validation."""


def test_create_via_form(auth_client):
    resp = auth_client.post("/things/new", data={
        "name": "Form Test",
        "value": "123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Form Test" in resp.data  # Verify it appears on the page


def test_create_rejects_empty_name(auth_client):
    resp = auth_client.post("/things/new", data={
        "name": "",
        "value": "123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    # Should show an error, not create the record
    assert b"required" in resp.data.lower() or b"error" in resp.data.lower()


def test_create_rejects_oversized_input(auth_client):
    resp = auth_client.post("/things/new", data={
        "name": "x" * 10000,
        "value": "123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    # Should handle gracefully, not crash
```

---

## AI Function Tests

AI functions are tested with a mock to avoid hitting the real API during tests. Test two things: that the function passes the right data to Claude, and that it handles Claude's response (including malformed responses) correctly.

```python
"""Test AI analysis functions with mocked API calls."""
import json
from unittest.mock import patch


MOCK_AI_RESPONSE = {
    "summary": "Test summary",
    "findings": [{"title": "Finding 1", "detail": "Detail", "severity": "low"}],
    "score": 75,
}


@patch("analysis._call_claude")
def test_ai_analyse_returns_structured_data(mock_claude):
    mock_claude.return_value = {
        "text": json.dumps(MOCK_AI_RESPONSE),
        "input_tokens": 100,
        "output_tokens": 50,
        "truncated": False,
    }
    from analysis import ai_analyse_thing
    result = ai_analyse_thing({"name": "Test"})
    assert result["score"] == 75
    assert len(result["findings"]) == 1


@patch("analysis._call_claude")
def test_ai_handles_markdown_fenced_json(mock_claude):
    mock_claude.return_value = {
        "text": f"```json\n{json.dumps(MOCK_AI_RESPONSE)}\n```",
        "input_tokens": 100,
        "output_tokens": 50,
        "truncated": False,
    }
    from analysis import ai_analyse_thing
    result = ai_analyse_thing({"name": "Test"})
    assert result["score"] == 75


@patch("analysis._call_claude")
def test_ai_handles_truncated_json(mock_claude):
    truncated = json.dumps(MOCK_AI_RESPONSE)[:50]  # Cut off mid-JSON
    mock_claude.return_value = {
        "text": truncated,
        "input_tokens": 100,
        "output_tokens": 4096,
        "truncated": True,
    }
    from analysis import ai_analyse_thing
    # Should either return a partial result or raise a clear ValueError
    try:
        result = ai_analyse_thing({"name": "Test"})
        assert isinstance(result, dict)  # Partial repair succeeded
    except ValueError as e:
        assert "not valid JSON" in str(e)  # Clear error, not a crash
```

---

## Per-Slice Testing Workflow

This extends the per-slice workflow in the main SKILL.md. After implementing a slice:

1. **Add new routes** to `test_smoke.py` route lists
2. **Add CRUD tests** if the slice introduced a new table or modified `db.py`
3. **Add form tests** if the slice introduced a new form submission
4. **Add AI mock tests** if the slice introduced a new AI function
5. **Run the full suite** — all existing tests must still pass (regression check)
6. **Present the updated test files** alongside the application files

The AI generates all test code. The human reviews and runs it. If a test fails, fix the application code (not the test) unless the test itself is wrong.

---

## Running Tests

From the project root:

```bash
# Run all tests with short output
pytest tests/ -v --tb=short

# Run just the smoke tests (fastest check)
pytest tests/test_smoke.py -v

# Run tests for a specific feature
pytest tests/test_things.py -v

# Stop on first failure (useful during development)
pytest tests/ -x -v
```

Expected output for a healthy project:
```
tests/test_smoke.py::test_public_routes PASSED
tests/test_smoke.py::test_protected_routes_redirect_when_unauthenticated PASSED
tests/test_smoke.py::test_protected_routes_load_when_authenticated PASSED
tests/test_db.py::test_create_and_read PASSED
tests/test_db.py::test_update PASSED
tests/test_db.py::test_delete PASSED
...
```

If any test returns a 500, that's a bug in the application — fix it before proceeding to the next slice.
