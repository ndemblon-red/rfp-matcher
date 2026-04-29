# RFP Matcher

An internal AI tool that matches incoming RFPs and project briefs against a library of past case studies, surfacing the most relevant examples for proposals and pitches.

Built with Flask, SQLite, python-pptx, and the Anthropic Claude API.

> 🚧 **Work in progress** — sync engine and library complete; matching engine in development.

---

## The Problem

Responding to RFPs at a consulting firm typically means:
- Manually searching through hundreds of slides looking for relevant past work
- Relying on individual memory of what projects exist
- Spending 1–3 hours per RFP just finding the right examples
- Inconsistent quality depending on who writes the proposal

## The Solution

A two-part internal tool:

1. **Sync Engine** — reads a live PowerPoint deck of case studies directly from SharePoint (via OneDrive sync), extracts structured data from each slide, and stores it in a local SQLite database. No manual data entry. Runs in under 30 seconds with no API calls.

2. **Matching Engine** — accepts an RFP document (PDF or DOCX) or a plain-text description, sends it to Claude to extract key requirements and themes, scores all case studies against those requirements, and returns the top 3–5 matches with plain-English explanations of why each one is relevant.

---

## Architecture

```
SharePoint (live PPTX)
        │
        ▼
  Sync Engine (sync.py)
  ┌─────────────────────────────────┐
  │ • shutil.copy2 → local temp     │
  │ • Detect case study slide range │
  │ • Extract title + full text     │
  │ • Deduplicate video variants    │
  │ • Local keyword inference       │
  │   (industry, AI type)           │
  │ • Content hash for incremental  │
  │   syncs (handles slide shifts)  │
  └──────────────┬──────────────────┘
                 │
                 ▼
          SQLite Database
                 │
        ┌────────┴────────┐
        ▼                 ▼
  Library View      Matching Engine (analysis.py)
  /library          ┌─────────────────────────────┐
                    │ • Upload PDF/DOCX or type    │
                    │   keywords                   │
                    │ • Claude API: extract themes │
                    │ • Score all case studies     │
                    │ • Return top 3–5 with        │
                    │   explanations               │
                    │ • Vision: identify client    │
                    │   logo on results only       │
                    └─────────────────────────────┘
```

---

## Key Technical Decisions

**Built on a predefined fullstack skill.** The architecture, stack, folder structure, and build methodology follow a company-standard fullstack skill — a reusable blueprint covering Flask patterns, database conventions, security requirements, logging, and a slice-based delivery methodology. This ensured consistency with other internal tools, avoided common pitfalls, and accelerated development significantly.

**No API calls during sync.** Industry and AI type are inferred using a local keyword lookup table — the industry label is already embedded in the slide heading (e.g. `COMMODITY PRICE FORECASTING (PETROCHEMICAL)`). This makes sync free, fast, and reliable. API calls are reserved for the matching step where they add real value.

**Slide number as primary key.** Each case study is keyed by its slide number in the PPTX. Content hashing handles the edge case where new slides are inserted alphabetically (shifting all subsequent numbers) — the hash detects unchanged content and updates the slide number without reprocessing.

**Live files via OneDrive sync.** The PPTX lives in SharePoint and is accessed via OneDrive sync. The sync script copies the file locally before opening it (`shutil.copy2`), avoiding OneDrive file locks entirely.

**Match on slide content, not metadata.** The matching engine scores against the full slide text — challenge, approach, results — not just tags or categories. This surfaces genuinely similar past work rather than superficial label matches.

---

## Project Structure

```
rfp-matcher/
├── app.py              # Flask app, routes, request lifecycle
├── sync.py             # PPTX sync engine
├── db.py               # Database layer (SQLite)
├── extraction.py       # PDF/DOCX text extraction
├── analysis.py         # Matching engine (Slice 5 — in progress)
├── PLAN.md             # Full build plan with slices and requirements
├── notes/              # Build retrospective and decision log
├── templates/          # Jinja2 HTML templates
├── static/             # CSS, JS, icons
├── tests/              # pytest test suite (32+ tests)
└── .env.example        # Environment variable template
```

---

## Status

| Slice | Description | Status |
|-------|-------------|--------|
| 1 | Foundation (Flask, logging, DB, tests) | ✅ Complete |
| 2 | Sync engine (PPTX → SQLite) | ✅ Complete |
| 3 | Case study library (browse, filter, search) | ✅ Complete |
| 4 | RFP upload + text extraction | ✅ Complete |
| 5 | Matching engine (Claude API) | 🔄 In progress |
| 6 | Polish (export, admin, user manual) | ⏳ Planned |

---

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite (dev), PostgreSQL (planned for production)
- **AI:** Anthropic Claude API (claude-sonnet-4-20250514)
- **Document parsing:** pdfplumber, python-docx, python-pptx
- **Testing:** pytest (32+ tests)
