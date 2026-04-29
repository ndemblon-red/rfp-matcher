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
A `/sync/run` POST endpoint that reads the PPTX, infers industry and AI type locally (no API
calls), and upserts case studies to SQLite. Unchanged slides are skipped via content hash.

### Changes
**sync.py:** `parse_pptx`, `_dedupe_video_variants`, `_infer_industry`, `_infer_ai_type`,
`infer_metadata`, `run_sync`, `_hash_content`
**db.py:** `case_studies` table (`title`, `slide_num`, `industry_full`, `ai_type`,
`slide_content`, `has_video`, `needs_review`, `content_hash`), `upsert_case_study`,
`content_hash_exists`, `log_sync_run`, `sync_runs` table
**app.py:** `/sync` GET route (status page), `/sync/run` POST route
**templates/sync.html:** sync trigger button, last-run stats
**tests/test_sync.py:** full suite covering parsing helpers, deduplication, local inference,
`run_sync` with all I/O mocked

### How to test
1. Set `PPTX_PATH` in `.env` and run the app
2. Navigate to `/sync` and click Sync Now
3. Check the result JSON shows `added > 0`
4. Sync again — all slides should show `unchanged`
```
pytest tests/test_sync.py -q   # all pass
```

### Technical debt
- SQLite used instead of PostgreSQL. Acceptable for a single-user internal tool; would need
  migration to PostgreSQL (and `psycopg2`) before multi-user or production deployment.

---

## Slice 3: Library
Priority: P1
Requirements covered: M1-04, M1-05
**Status: COMPLETE**

### What it delivers
A sortable, filterable case study table at `/library` and a detail view at `/library/<id>`.
Users can search by name or industry and sort by any column.

### Changes
**app.py:** `/library` GET, `/library/<int:case_id>` GET
**db.py:** `get_all_case_studies`, `get_case_study`, `get_distinct`, `get_case_study_count`,
`get_last_sync`
**templates/library.html:** sortable table (Slide #, Project Name, Industry, AI Type, Video),
search input, industry / AI type dropdowns, row count
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
Users can upload a PDF or DOCX at `/match`, see extracted text in a preview page, then
proceed to analysis (stub — implemented in Slice 5).

### Changes
**extraction.py:** `save_upload`, `extract_text` (pdfplumber for PDF, python-docx for DOCX)
**app.py:** `/match` GET, `/match/upload` POST, `/match/preview` GET, `/match/analyze` POST (stub)
**templates/match.html:** file upload form
**templates/match_preview.html:** extracted text preview, word count, Analyze button

### How to test
1. Open `/match` and upload a PDF — preview page shows extracted text
2. Upload a DOCX — same result
3. Upload a `.txt` file — rejected with an error flash
4. Upload with no file selected — rejected with an error flash

---

## Slice 5: Matching Engine
Priority: P1
Requirements covered: M2-03, M3-01, M3-02, M3-03, M3-04, M3-05
**Status: NOT STARTED**

### What it delivers
The `/match/analyze` endpoint becomes real: it sends RFP text to Claude, scores all case
studies, and renders a ranked results page showing the top 3–5 matches with explanations.
A keyword input field on the match page lets users skip file upload entirely. Client logos
are identified via Claude vision at match time and cached in the DB.

### Changes
**analysis.py** *(new file)*:
- `extract_requirements(rfp_text) → dict` — Claude API call; returns extracted themes,
  industry signals, and key capability keywords
- `score_case_studies(requirements, case_studies) → list[dict]` — score each case study
  against extracted requirements; return ranked list with `score` and `explanation` fields
- `identify_client_logo(pptx_path, slide_num) → str | None` — Claude vision call;
  identifies client from slide logo image

**db.py:**
- Add `logo_name TEXT` column to `case_studies` (cached vision result)
- Add `get_logo_name(case_id)` and `set_logo_name(case_id, name)` for cache read/write

**app.py:**
- `/match` GET — add keyword text input alongside file upload form
- `/match/analyze` POST — implement: read RFP text from session or keyword input, call
  `extract_requirements`, call `score_case_studies`, run `identify_client_logo` for each
  result (checking cache first), render results
- `/match/results` GET — render stored results (so the page survives a refresh)
- Add Flask-WTF CSRF protection to all POST endpoints

**templates/match.html:** add keyword textarea as alternative to file upload
**templates/match_results.html** *(new)*: ranked result cards, each showing project name,
industry, AI type, client (from logo cache), match explanation, and a link to the library
detail page

**requirements.txt:** add `flask-wtf`

**tests/test_analysis.py** *(new)*:
- `test_extract_requirements_returns_expected_keys` — mock Claude call, assert dict shape
- `test_score_case_studies_ranks_by_score` — no API call; pure function
- `test_score_case_studies_returns_top_n` — assert at most 5 results
- `test_identify_client_logo_returns_cached` — assert DB hit skips API call
- `test_identify_client_logo_calls_api_on_miss` — assert API called when no cache

**tests/test_smoke.py:** add `/match/results` and `/match/analyze` route tests

### How to test
1. Open `/match`, type keywords into the text area (no file), click Analyse
2. Results page shows 3–5 case studies with explanations
3. Upload a real RFP PDF — results page shows relevant matches
4. Run analysis twice on the same slide — confirm only one Claude vision call is made
   (logo_name cached in DB)
5. Check browser network tab: CSRF token present on all POST requests

### Notes
- If `app.py` exceeds ~400 lines after this slice, extract match routes into
  `routes/match.py` (Flask Blueprint) before Slice 6.
- CSRF protection added here; retrofit to `/sync/run` and `/match/upload` at the same time.

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
| `updated` counter increments on first sync of a fresh DB (content hash mismatch on re-sync with empty hash) | Low | Fix in Slice 5 or as a standalone patch before going live |
| SQLite instead of PostgreSQL | Medium | Acceptable for single-user internal use; migrate before multi-user or production deployment |
| No authentication | Low (deliberate) | Internal tool on trusted network; document this decision. If access needs to be restricted, add Flask-Login in a dedicated auth slice |
| CSRF protection not yet implemented | Medium | Implement in Slice 5 with Flask-WTF; retrofit all existing POST endpoints at the same time |
| `app.py` blueprint threshold | Low | Currently 236 lines / 9 routes. Slice 5 adds ~2 routes and ~100 lines — within budget. Reassess after Slice 5 |
