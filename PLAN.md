# RFP Matcher — Build Plan

Internal tool for ADL Catalyst. Matches uploaded RFPs against the case study library to surface
the most relevant past projects for a pitch or proposal.

---

## Modules and Requirements

### Module 1: Case Study Library
| ID | Requirement |
|----|-------------|
| M1-01 | Sync case studies from PPTX into SQLite: detect slide range between section dividers and Appendix, extract title from `CASE STUDIES \|` heading, deduplicate video variants |
| M1-02 | Infer industry and AI type locally (no API): bracket extraction from title, keyword fallback on slide text |
| M1-03 | Incremental sync: skip unchanged slides via content hash; track added / updated / unchanged counters |
| M1-04 | Browse case studies in a sortable, filterable table (industry, AI type, video flag) |
| M1-05 | View individual case study detail (full slide content, metadata) |

### Module 2: RFP Ingestion
| ID | Requirement |
|----|-------------|
| M2-01 | Upload PDF or DOCX; validate extension and file size; extract text with pdfplumber / python-docx |
| M2-02 | Preview extracted text with word count before running analysis |
| M2-03 | Accept plain-text keyword input directly (no file required) as an alternative entry point |

### Module 3: Matching Engine
| ID | Requirement |
|----|-------------|
| M3-01 | Send RFP text to Claude API; extract key requirements, themes, industry signals |
| M3-02 | Score all case studies against extracted requirements (industry match, AI type match, keyword overlap in slide content) |
| M3-03 | Return top 3–5 ranked results, each with a brief plain-English explanation of why it matches |
| M3-04 | Identify client from slide logo via Claude vision at match time only; cache result in DB to avoid repeat API calls |
| M3-05 | Add CSRF protection to all POST endpoints |

### Module 4: Polish
| ID | Requirement |
|----|-------------|
| M4-01 | Export matched results as a formatted document (DOCX or PDF) |
| M4-02 | Admin flag: mark a case study as needing review; surface flagged records in library |
| M4-03 | User manual covering sync, upload, and match workflows |

---

## Dependency Graph

```
Slice 1 (Foundation)
    └── Slice 2 (Sync Engine)
            └── Slice 3 (Library)
                    └── Slice 4 (RFP Upload)
                                └── Slice 5 (Matching Engine)
                                            └── Slice 6 (Polish)
```

---

## Slices

---

## Slice 1: Foundation
Priority: P1
Requirements covered: infrastructure (no module requirement IDs — cross-cutting)
**Status: COMPLETE**

### What it delivers
A running Flask app with logging, security headers, session config, DB initialisation, and a
working pytest harness. No features yet — just a solid base every later slice builds on.

### Changes
**app.py:** Flask app factory, `before_request` / `after_request` hooks, security headers,
session config, error handlers (404, 413, 500)
**db.py:** `get_conn()`, `init_db()`, WAL mode, foreign keys
**tests/conftest.py:** `app` fixture, `client` fixture, `setup_db` fixture (in-memory SQLite)
**tests/test_smoke.py:** reachability tests for all routes

### How to test
```
pytest tests/ -q   # all pass
```

---

## Slice 2: Sync Engine
Priority: P1
Requirements covered: M1-01, M1-02, M1-03
**Status: COMPLETE**

### What it delivers
A `/sync/run` POST endpoint that reads the PPTX, infers industry and engagement type locally
(with Claude Haiku fallback when keywords don't match), and upserts case studies to SQLite.
Unchanged slides are skipped via content hash; slides that moved positions are detected and
updated. Embeddings are generated automatically after each sync — only for records added or
updated in that run (not the full library). Sync result shows how many embeddings were
generated alongside the usual added/updated/skipped counts.

### Changes
**sync.py:** `parse_pptx`, `_dedupe_video_variants`, `_infer_industry`, `_infer_engagement_type`,
`_classify_via_claude` (Haiku fallback), `infer_metadata`, `run_sync`, `_hash_content`.
`run_sync` collects IDs of added/updated records and passes `case_ids` to `store_embeddings`.
**db.py:** `case_studies` table (`title`, `slide_num`, `industry_full`, `engagement_type`,
`slide_content`, `challenge`, `approach`, `results`, `has_video`, `needs_review`,
`content_hash`, `embedding`, `embedding_model`), `upsert_case_study` (returns `(action, id)`
tuple), `content_hash_exists`, `get_case_study_by_hash`, `update_slide_num`, `log_sync_run`,
`sync_runs` table, `_migrate_schema` (handles column renames and schema upgrades),
`get_case_studies_without_embeddings(case_ids=None)` (accepts optional ID filter).
**app.py:** `/sync` GET, `/sync/run` POST
**templates/sync.html:** single "Run Sync" button; result shows Added / Updated / Skipped / Embedded counts
**tests/test_sync.py:** full suite covering parsing helpers, deduplication, local inference,
`run_sync` with all I/O mocked

### How to test
1. Set `PPTX_PATH` in `.env` and run the app
2. Navigate to `/sync` and click Run Sync
3. Check the result JSON shows `added > 0`
4. Sync again — all slides should show `unchanged`
```
pytest tests/test_sync.py -q   # all pass
```

### Technical debt
- `ai_type` column renamed to `engagement_type` post-plan; handled by schema migration in `db.py`.
- SQLite used instead of PostgreSQL. Acceptable for single-user; migrate before multi-user deployment.

---

## Slice 3: Library
Priority: P1
Requirements covered: M1-04, M1-05
**Status: COMPLETE**

### What it delivers
A sortable, filterable case study table at `/library` and a detail view at `/library/<id>`.
Users can search by name or industry, filter by engagement type, and sort by any column.

### Changes
**app.py:** `/library` GET, `/library/<int:case_id>` GET
**db.py:** `get_all_case_studies`, `get_case_study`, `get_distinct`, `get_case_study_count`,
`get_last_sync`
**templates/library.html:** sortable table (Slide #, Project Name, Industry, Engagement Type,
Video), search input, industry / engagement type dropdowns, row count
**templates/library_detail.html:** full case study detail card

### How to test
1. Run a sync so records exist
2. Open `/library` — table shows all case studies
3. Type in the search box — rows filter live
4. Select an industry from the dropdown — only matching rows shown
5. Click a column header — rows sort ascending / descending
6. Click a project name — detail page loads with full content

---

## Slice 4: RFP Upload
Priority: P1
Requirements covered: M2-01, M2-02
**Status: COMPLETE**

### What it delivers
Users can upload a PDF or DOCX at `/match`, see a structured AI-generated brief in a preview
page (objective, challenges, capabilities needed, context), then proceed to analysis.
Drag-and-drop is supported; brief generation failures degrade gracefully.

### Changes
**extraction.py:** `save_upload`, `extract_text` (pdfplumber for PDF, python-docx for DOCX)
**analysis.py:** `generate_brief` — called during upload to power the structured preview
**app.py:** `/match` GET, `/match/upload` POST, `/match/preview` GET
**templates/match.html:** file upload form with drag-and-drop, keyword textarea, loading state
**templates/match_preview.html:** structured brief (objective, challenges, capabilities, context),
word count, Analyse button with loading state

### How to test
1. Open `/match` and upload a PDF — brief preview page shows structured analysis
2. Upload a DOCX — same result
3. Upload a `.txt` file — rejected with an error flash
4. Upload with no file selected — rejected with an error flash

---

## Slice 5: Matching Engine
Priority: P1
Requirements covered: M2-03, M3-01, M3-02, M3-03 ✅ | M3-04, M3-05 ❌ outstanding
**Status: PARTIAL**

### What is implemented

**M2-03 — Keyword input** ✅
Textarea on `/match` accepts a plain-text description; submit goes directly to `/match/analyze`
bypassing file upload.

**M3-01 — RFP brief extraction** ✅
`generate_brief(rfp_text)` calls Claude Sonnet to return `{is_relevant, objective, challenges,
capabilities_needed, context}`. `is_relevant` is false when the input is clearly not a business
RFP or project brief; `/match/analyze` checks this before scoring and redirects early with a
flash message. Called during upload (for preview) and during keyword-only analysis. Handles
truncated responses via `_safe_parse_json` with JSON repair.

**M3-02 + M3-03 — Scoring and results** ✅
`match_case_studies(rfp_text, case_studies, brief_capabilities, brief)` uses a two-step pipeline:
- **Step 1 (free):** OpenAI `text-embedding-3-small` cosine similarity pre-selects top 10
  candidates from the full library. Falls back to sending all case studies when no embeddings
  are stored.
- **Step 2 (Claude Sonnet):** Deep reasoning scores each candidate 0–100 with strict rubric;
  returns `score`, `explanation` (starts with key difference), and `matched_caps`.
  Threshold: only scores > 25 are returned; max 5 results.
`_extract_sections` parses Challenge/Approach/Results blocks from slide content and sends only
those sections (not raw text) to Claude to reduce noise.

**Embeddings pipeline** ✅
`store_embeddings()` generates and persists embeddings for all case studies lacking one.
Runs automatically after each sync; also available manually via `/sync/embed` POST.
Stored as float32 BLOB in `case_studies.embedding`; model name in `embedding_model`.

**`/match/analyze` POST** ✅ — reads from session (file upload path) or keyword input,
runs `generate_brief` + checks `is_relevant` flag (redirects with flash if false) +
`match_case_studies`, stores results in session.

**`/match/results` GET** ✅ — renders stored results; redirects to `/match` if no session data.

**`match_results.html`** ✅ — result cards with score badge (colour-coded by tier), industry /
engagement type badges, video flag, matched capability pills, link to detail. Explanation is
split into two labelled lines: **Difference** (the key difference sentence from Claude) and
**Why it fits** (the remaining sentences). Falls back to showing the raw explanation text if
the "Key difference:" prefix is absent.

**Tests** ✅
- `tests/test_analysis.py`: `_extract_sections` (8 cases), `match_case_studies` (10 cases),
  `generate_brief` (3 cases)
- `tests/test_embeddings.py`: cosine similarity, serialisation roundtrip, embedding text
  builders, `generate_embedding`, `store_embeddings`, embedding pre-selection integration (5 cases)
- `tests/test_smoke.py`: keyword analysis, results page (session), results redirect (no session)

---

### What is still outstanding

**M3-04 — Client logo identification** ❌
Claude vision call to identify client name from slide logo images. No `identify_client_logo`
function exists; no `logo_name` column in DB. Deferred — low impact as project titles are
already shown.

**M3-05 — CSRF protection** ❌
`flask-wtf` is not in `requirements.txt`. No CSRF tokens in any template. All POST endpoints
(`/sync/run`, `/sync/embed`, `/match/upload`, `/match/analyze`) are currently unprotected.
**This should be implemented before the tool is shared more broadly.**

---

### Notes
- `app.py` is currently 308 lines / 10 routes. Still within budget; reassess after Slice 6.
- The original plan named this function `extract_requirements`; it was implemented as
  `generate_brief` with a richer output schema.

---

## Evals
Priority: P1 (ongoing)
**Status: COMPLETE**

### What it delivers
`evals/run_evals.py` — a standalone eval script covering three categories across 10 assertions.
Run with `python evals/run_evals.py` after populating `evals/fixtures/` with the two RFP files.

### Categories
| # | Category | Method | PASS condition |
|---|----------|--------|----------------|
| 1 | Off-topic guard (×5) | No AI judge | `match_case_studies` returns 0 results > 25 for nonsense input |
| 2 | Brief quality (×2) | AI-as-judge (Sonnet) | Judge scores brief ≥ 3/5 |
| 3 | Match quality: E.ON results | Score threshold | ≥ 2 results score > 50 |
| 3 | Match quality: Nkom no match | Score threshold | 0 results score > 40 |
| 3 | Match quality: E.ON top match | AI-as-judge (Sonnet) | Judge answers "yes" |

### Notes
- Fixture files (`evals/fixtures/*.pdf` / `*.txt`) are gitignored — drop either format
- Token tracking monkey-patches `analysis._call_claude`; cost estimate printed at end
- Script exits 0 if all pass, 1 if any fail (CI-friendly)
- Skips gracefully when DB is empty or fixtures are missing

---

## Slice 6: Polish
Priority: P2
Requirements covered: M4-01, M4-02, M4-03
**Status: NOT STARTED**

### What it delivers
Export matched results as a DOCX, surface `needs_review` flagged records in the library,
and a user manual covering all three workflows.

### Changes
**report.py** *(new file)*: `export_results_docx(results) → BytesIO` — generates a
formatted DOCX with match summary, project cards, and explanations

**app.py:**
- `/match/export` POST — call `export_results_docx`, return as file download
- `/library` GET — add `needs_review` filter tab / indicator badge

**templates/match_results.html:** add Export button
**templates/library.html:** add needs-review badge and filter

**tests/test_report.py** *(new)*: `test_export_produces_valid_docx` — assert output is
non-empty bytes parseable by python-docx

### How to test
1. Run an analysis, click Export — browser downloads a `.docx` file
2. Open the file — project cards are formatted correctly
3. In the library, the needs-review filter shows only flagged records

---

## Known Issues / Technical Debt

| Issue | Severity | Plan |
|-------|----------|------|
| `updated` counter increments on first sync of a fresh DB (content hash mismatch on re-sync with empty hash) | Low | Fix before going live |
| SQLite instead of PostgreSQL | Medium | Acceptable for single-user internal use; migrate before multi-user or production deployment |
| No authentication | Low (deliberate) | Internal tool on trusted network; document this decision. Add Flask-Login if access needs restricting |
| CSRF protection not yet implemented | Medium | Implement in Slice 5 remainder with Flask-WTF; retrofit `/sync/run`, `/sync/embed`, `/match/upload`, `/match/analyze` |
| Client logo identification (M3-04) not implemented | Low | Deferred; project titles already shown. Implement in a separate slice if client branding matters |
| `app.py` blueprint threshold | Low | Currently 308 lines / 10 routes. Reassess after Slice 6 |
