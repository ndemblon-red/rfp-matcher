# Database Patterns Reference

This file contains all PostgreSQL and psycopg2 patterns for ADL Catalyst applications. Read this file when creating or modifying `db.py` or any database-related code.

## Table of Contents

1. [Connection Management](#connection-management)
2. [Table Creation](#table-creation)
3. [Schema Migrations](#schema-migrations)
4. [CRUD Pattern](#crud-pattern)
5. [Common Pitfalls](#common-pitfalls)

---

## Connection Management

Use environment variables for all connection parameters. Never hardcode credentials.

```python
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )
```

Every function that touches the database follows the pattern: `get_conn()` → `try` / `with cursor` / `finally conn.close()`. Never leave connections open.

---

## Table Creation

Always use `IF NOT EXISTS` so the app can safely restart without migration scripts:

```sql
CREATE TABLE IF NOT EXISTS table_name (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    ...
);
```

Call all `CREATE TABLE` statements from an `init_db()` function invoked at app startup.

---

## Schema Migrations

### Additive migrations (the default)

Use additive migrations for new columns, new tables, and new indexes. These are safe to run repeatedly and belong inside `init_db()`:

```sql
DO $$ BEGIN
    ALTER TABLE table_name ADD COLUMN IF NOT EXISTS new_col TYPE DEFAULT value;
EXCEPTION WHEN others THEN NULL;
END $$;
```

Place migration blocks inside `init_db()` after the corresponding `CREATE TABLE`. They run idempotently on every startup.

### Destructive migrations (column renames, type changes, drops, backfills)

Never embed destructive changes in `init_db()`. Instead, write a standalone migration script in a `migrations/` directory.

**Directory structure:**

```
project_name/
├── migrations/
│   ├── 001_rename_status_to_state.sql
│   ├── 002_convert_score_to_numeric.sql
│   └── README.md       # Documents each migration and when to run it
├── db.py
├── ...
```

**Naming convention:** `NNN_short_description.sql` — zero-padded sequence number, lowercase with underscores. Run them in order.

**Migration script template:**

```sql
-- Migration 001: Rename status column to state
-- Run ONCE against the database: psql -d $DB_NAME -f migrations/001_rename_status_to_state.sql
-- Date: 2025-06-15
-- Reason: "status" conflicts with a reserved word in the reporting module

BEGIN;

-- Step 1: Add the new column
ALTER TABLE things ADD COLUMN IF NOT EXISTS state VARCHAR(50);

-- Step 2: Copy data from old to new
UPDATE things SET state = status WHERE state IS NULL;

-- Step 3: Set default on new column
ALTER TABLE things ALTER COLUMN state SET DEFAULT 'draft';

-- Step 4: Drop the old column (only after verifying step 2 worked)
ALTER TABLE things DROP COLUMN IF EXISTS status;

COMMIT;
```

Key rules for destructive migrations:
- Always wrap in `BEGIN` / `COMMIT` so the migration is atomic — if any step fails, nothing changes.
- Add the new column first, copy data, then drop the old one. Never rename directly with `ALTER COLUMN RENAME` in production — a two-step add-copy-drop is safer because the app can work with either column during the transition.
- Include a comment header with the date, what it does, and why. The next person reading this (or Claude in a future slice) needs context.
- Document the migration in `migrations/README.md` with the command to run it.

**Common destructive scenarios:**

| Change needed | Migration approach |
|---------------|-------------------|
| Rename a column | Add new column → copy data → drop old column |
| Change column type (e.g. VARCHAR → INTEGER) | Add new column with new type → cast and copy data → drop old column |
| Backfill a new column with computed data | Add column in `init_db()` (additive) → write migration to populate existing rows |
| Drop a table or column no longer used | Migration script with `DROP TABLE IF EXISTS` / `DROP COLUMN IF EXISTS` |
| Add a NOT NULL constraint to existing column | Migration to fill NULLs with a default first, then `ALTER COLUMN SET NOT NULL` |

**When to trigger a destructive migration during a build:**

If a slice requires a schema change that isn't purely additive, insert a migration step into the slice plan:

```
### Changes
**migrations/003_rename_priority_to_severity.sql:** Renames priority → severity on findings table
**db.py:** Update all queries to use "severity" instead of "priority"
**templates/findings.html:** Update column header

### How to test
1. Run: psql -d $DB_NAME -f migrations/003_rename_priority_to_severity.sql
2. Verify: psql -d $DB_NAME -c "SELECT severity FROM findings LIMIT 1;"
3. Restart app and confirm findings page loads correctly
```

The user runs the migration script manually before testing the slice. This keeps the human in the loop for any data-altering operation.

---

## CRUD Pattern

Every CRUD function follows this structure. Use `RealDictCursor` so results come back as dictionaries:

```python
def get_thing(thing_id):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM things WHERE id = %s", (thing_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def create_thing(name, value):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO things (name, value) VALUES (%s, %s) RETURNING id",
                (name, value),
            )
            thing_id = cur.fetchone()[0]
            conn.commit()
            return thing_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_thing(thing_id, name, value):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE things SET name = %s, value = %s, updated_at = NOW() WHERE id = %s",
                (name, value, thing_id),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_thing(thing_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM things WHERE id = %s", (thing_id,))
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Key rules:
- Always use parameterised queries (`%s` placeholders) — never use f-strings or string concatenation for SQL values. This prevents SQL injection.
- Always `conn.commit()` after writes.
- Always `conn.rollback()` in the `except` block for writes.
- Always `conn.close()` in `finally`.

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| Data doesn't persist after INSERT | Missing `conn.commit()` | Add `conn.commit()` after write operations |
| `connection already closed` errors | Reusing a closed connection | Always call `get_conn()` fresh per function call |
| Slow under concurrent users | No connection pooling | See note below |

**Connection pooling note:** The `get_conn()` / `conn.close()` pattern is simple and correct for PoCs and low-concurrency apps (< ~50 concurrent users). For higher concurrency, replace `get_conn()` with a connection pool using `psycopg2.pool.ThreadedConnectionPool` or switch to `psycopg3` with its built-in async pool. Don't prematurely optimise — start simple and pool when you observe connection latency.
