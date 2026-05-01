import sqlite3
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "rfp_matcher.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_COL_ORDER = [
    "id", "title", "slide_num", "industry_full", "engagement_type",
    "slide_content", "challenge", "approach", "results",
    "has_video", "needs_review", "content_hash", "embedding", "embedding_model", "synced_at",
]
_COL_DEFAULTS = {
    "slide_num":       "NULL",
    "has_video":       "0",
    "challenge":       "NULL",
    "approach":        "NULL",
    "results":         "NULL",
    "content_hash":    "NULL",
    "engagement_type": "NULL",
    "embedding":       "NULL",
    "embedding_model": "NULL",
}
# Maps new column name → old column name for schema migrations involving renames.
_COL_RENAMES = {"engagement_type": "ai_type"}
_NEW_TABLE_DDL = """
    CREATE TABLE case_studies_new (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        title           TEXT NOT NULL,
        slide_num       INTEGER,
        industry_full   TEXT,
        engagement_type TEXT,
        slide_content   TEXT,
        challenge       TEXT,
        approach        TEXT,
        results         TEXT,
        has_video       INTEGER DEFAULT 0,
        needs_review    INTEGER DEFAULT 0,
        content_hash    TEXT,
        embedding       BLOB,
        embedding_model TEXT,
        synced_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(slide_num)
    )
"""


def _migrate_schema(conn):
    """Migrate case_studies to current schema if needed."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='case_studies'")
    if not cur.fetchone():
        return

    cur.execute("PRAGMA table_info(case_studies)")
    existing_cols = {row[1] for row in cur.fetchall()}

    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='case_studies'")
    row = cur.fetchone()
    current_sql = row[0] if row and row[0] else ""

    needs_migration = (
        not {"has_video", "challenge", "approach", "results", "slide_num",
             "content_hash", "engagement_type"}.issubset(existing_cols)
        or "client" in existing_cols
        or "UNIQUE(slide_num)" not in current_sql
    )
    if not needs_migration:
        return

    logger.info("Migrating case_studies schema to current version")
    cur.execute("DROP TABLE IF EXISTS case_studies_new")
    cur.execute(_NEW_TABLE_DDL)

    select_parts = []
    for c in _COL_ORDER:
        if c in existing_cols:
            select_parts.append(c)
        elif _COL_RENAMES.get(c) in existing_cols:
            select_parts.append(_COL_RENAMES[c])
        else:
            select_parts.append(_COL_DEFAULTS.get(c, "NULL"))
    cur.execute(
        f"INSERT INTO case_studies_new ({', '.join(_COL_ORDER)}) "
        f"SELECT {', '.join(select_parts)} FROM case_studies"
    )
    migrated = cur.rowcount
    cur.execute("DROP TABLE case_studies")
    cur.execute("ALTER TABLE case_studies_new RENAME TO case_studies")
    conn.commit()
    logger.info("Schema migration complete: %d rows preserved", migrated)


def _add_column_if_missing(conn, column, definition):
    """Add a column to case_studies if it does not already exist."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(case_studies)")
    cols = {row[1] for row in cur.fetchall()}
    if column not in cols:
        cur.execute(f"ALTER TABLE case_studies ADD COLUMN {column} {definition}")
        conn.commit()
        logger.info("Added column %s to case_studies", column)


def init_db():
    conn = get_conn()
    try:
        _migrate_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_studies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                slide_num       INTEGER,
                industry_full   TEXT,
                engagement_type TEXT,
                slide_content   TEXT,
                challenge       TEXT,
                approach        TEXT,
                results         TEXT,
                has_video       INTEGER DEFAULT 0,
                needs_review    INTEGER DEFAULT 0,
                content_hash    TEXT,
                embedding       BLOB,
                embedding_model TEXT,
                synced_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(slide_num)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                added       INTEGER DEFAULT 0,
                updated     INTEGER DEFAULT 0,
                skipped     INTEGER DEFAULT 0,
                warnings    TEXT
            )
        """)
        conn.commit()
        # Additive migrations for DBs that predate the embedding columns.
        _add_column_if_missing(conn, "embedding", "BLOB")
        _add_column_if_missing(conn, "embedding_model", "TEXT")
        logger.info("Database initialised at %s", DB_PATH)
    finally:
        conn.close()


def get_all_case_studies():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, slide_num, title, industry_full, engagement_type, has_video, needs_review, synced_at
            FROM case_studies
            ORDER BY slide_num, title
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_case_study(case_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM case_studies WHERE id = ?", (case_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_distinct(field):
    allowed = {"industry_full", "engagement_type"}
    if field not in allowed:
        raise ValueError(f"Invalid field: {field}")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT DISTINCT {field} FROM case_studies "
            f"WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def content_hash_exists(content_hash):
    """Return True if any record in case_studies already has this content_hash."""
    if not content_hash:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM case_studies WHERE content_hash = ?", (content_hash,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def upsert_case_study(title, slide_num, industry_full, engagement_type, slide_content,
                      challenge, approach, results, has_video=0, needs_review=0,
                      content_hash=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM case_studies WHERE slide_num = ?",
            (slide_num,),
        )
        exists = cur.fetchone() is not None
        if exists:
            # Content changed — clear stale embedding so it gets regenerated on next store_embeddings().
            cur.execute("""
                UPDATE case_studies SET
                    title           = ?,
                    industry_full   = ?,
                    engagement_type = ?,
                    slide_content   = ?,
                    challenge       = ?,
                    approach        = ?,
                    results         = ?,
                    has_video       = ?,
                    needs_review    = ?,
                    content_hash    = ?,
                    embedding       = NULL,
                    embedding_model = NULL,
                    synced_at       = CURRENT_TIMESTAMP
                WHERE slide_num = ?
            """, (title, industry_full, engagement_type, slide_content,
                  challenge, approach, results, has_video, needs_review, content_hash,
                  slide_num))
        else:
            cur.execute("""
                INSERT INTO case_studies
                    (title, slide_num, industry_full, engagement_type, slide_content,
                     challenge, approach, results, has_video, needs_review, content_hash, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (title, slide_num, industry_full, engagement_type, slide_content,
                  challenge, approach, results, has_video, needs_review, content_hash))
        conn.commit()
        return "updated" if exists else "added"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_case_study_by_hash(content_hash):
    """Return {id, slide_num} for the record matching content_hash, or None."""
    if not content_hash:
        return None
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, slide_num FROM case_studies WHERE content_hash = ?",
            (content_hash,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_slide_num(case_id, slide_num):
    """Update the slide_num for an existing case study. No-op if the position is already taken."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE case_studies SET slide_num = ? WHERE id = ?",
            (slide_num, case_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        logger.warning(
            "Could not update slide_num to %d for case_study id=%d — position already taken",
            slide_num, case_id,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log_sync_run(added, updated, skipped, warnings=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sync_runs (added, updated, skipped, warnings) VALUES (?, ?, ?, ?)",
            (added, updated, skipped, warnings),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_last_sync():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sync_runs ORDER BY ran_at DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_case_studies_for_scoring():
    """Return all case studies with slide_content and embedding, for use by the matching engine."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, industry_full, engagement_type, has_video, slide_content, embedding
            FROM case_studies
            ORDER BY slide_num, title
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_case_studies_without_embeddings():
    """Return {id, title, slide_content} for case studies that have no stored embedding."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, slide_content
            FROM case_studies
            WHERE embedding IS NULL
            ORDER BY id
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def store_case_study_embedding(case_id, embedding_blob, model_name):
    """Persist a serialised embedding BLOB and its model name for one case study."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE case_studies SET embedding = ?, embedding_model = ? WHERE id = ?",
            (embedding_blob, model_name, case_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_case_study_count():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM case_studies")
        return cur.fetchone()[0]
    finally:
        conn.close()
