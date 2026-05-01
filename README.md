# RFP Matcher

An internal AI tool that matches incoming RFPs and project briefs against a library of past case studies, surfacing the most relevant examples for proposals and pitches.

Built with Flask, SQLite, python-pptx, the Anthropic Claude API, and OpenAI embeddings.

> 🚧 **Work in progress** — sync engine, library, and matching engine complete; polish slice planned.

---

## The Problem

Responding to RFPs at a consulting firm typically means:
- Manually searching through hundreds of slides looking for relevant past work
- Relying on individual memory of what projects exist
- Spending 1–3 hours per RFP just finding the right examples
- Risk of proposing weak analogies because you don't know what you don't know

## The Solution

A three-part internal tool:

1. **Sync Engine** — reads a live PowerPoint deck of case studies directly from SharePoint (via OneDrive sync), extracts structured data from each slide, generates semantic embeddings, and stores everything in a local SQLite database. No manual data entry. Runs in under 30 seconds with no LLM API calls.

2. **Structured Brief** — when a user uploads an RFP or types a description, Claude generates a structured brief (objective, challenges, capabilities needed, context) that the user reviews before matching. This catches misunderstandings early and makes the tool transparent.

3. **Matching Engine** — two-step semantic pipeline: OpenAI embeddings find the top 10 genuinely similar cases by vector cosine similarity, then Claude does deep reasoning on those 10 to produce ranked results with scores, similarities, key differences, and matched capability tags.

---

## Architecture

```
SharePoint (live PPTX)
        │
        ▼
  Sync Engine (sync.py)
  ┌──────────────────────────────────────┐
  │ • shutil.copy2 → local temp          │
  │ • Detect slide range (dividers)      │
  │ • Extract title + sections           │
  │ • Deduplicate video variants         │
  │ • Local keyword inference            │
  │   (industry, engagement type)        │
  │ • Content hash → incremental syncs   │
  │ • OpenAI embeddings stored in DB     │
  └──────────────┬───────────────────────┘
                 │
                 ▼
          SQLite Database
                 │
        ┌────────┴─────────┐
        ▼                  ▼
  Library View       Matching Engine (analysis.py)
  /library           ┌──────────────────────────────┐
                     │ Upload PDF/DOCX or type query │
                     │                               │
                     │ Step 0: generate_brief()      │
                     │ → structured brief preview    │
                     │                               │
                     │ Step 1: cosine similarity     │
                     │ → embed RFP brief             │
                     │ → compare vs all embeddings   │
                     │ → top 10 candidates (free)    │
                     │                               │
                     │ Step 2: Claude Sonnet         │
                     │ → deep reasoning on top 10    │
                     │ → score, similarities,        │
                     │   differences, matched_caps   │
                     │ → filter: score > 25 only     │
                     └──────────────────────────────┘
```

---

## Key Technical Decisions

**Built on a predefined fullstack skill.** The architecture, stack, folder structure, and build methodology follow a company-standard fullstack skill — a reusable blueprint covering Flask patterns, database conventions, security requirements, logging, and a slice-based delivery methodology. This ensured consistency with other internal tools, avoided common pitfalls, and accelerated development significantly.

**Embeddings prevent false positives.** The matching engine uses OpenAI `text-embedding-3-small` to pre-filter candidates by semantic similarity before Claude scores them. This is the critical design decision — keyword-based pre-filtering was tried first and produced confident-sounding but wrong results (a Norwegian telecom regulatory tender scored 75% against an IT cost review because both mentioned "cost modelling"). Embeddings correctly place these far apart in vector space, so Claude never sees them as candidates.

**No LLM calls during sync.** Industry and engagement type are inferred using a local keyword lookup table — the industry label is already in the slide heading (e.g. `COMMODITY PRICE FORECASTING (PETROCHEMICAL)`). Claude Haiku is used as a fallback only for slides the keyword lookup can't categorise, and results are cached permanently. This makes sync free, fast, and reliable.

**Slide number as primary key.** Each case study is keyed by its slide number. Content hashing handles the edge case where new slides are inserted alphabetically (shifting all subsequent numbers) — the hash detects unchanged content and updates the slide number without reprocessing.

**Live files via OneDrive sync + shutil.copy2.** The PPTX lives in SharePoint and is accessed via OneDrive sync. The sync script copies the file locally before opening it, avoiding OneDrive file locks entirely.

**Match on content, not metadata.** Embeddings and Claude reasoning operate on the Challenge/Approach/Results sections of each slide — not on industry tags or engagement type labels. Two projects in different industries with the same underlying business problem will score higher than two projects in the same industry with different problems.

**Key differences are shown explicitly.** Each result card shows not just why a case is relevant but also the key difference. This actively discourages weak matches by making the gap visible to the user.

---

## Project Structure

```
rfp-matcher/
├── app.py              # Flask app, routes, request lifecycle
├── sync.py             # PPTX sync engine + embedding generation
├── db.py               # Database layer (SQLite)
├── extraction.py       # PDF/DOCX text extraction
├── analysis.py         # Brief generation, embedding, matching engine
├── PLAN.md             # Full build plan with slices and requirements
├── docs/               # Architecture decision records
├── notes/              # Build retrospective and session notes
├── templates/          # Jinja2 HTML templates
├── static/             # CSS, JS, icons
├── tests/              # pytest test suite (129 tests)
└── .env.example        # Environment variable template
```

---

## Status

| Slice | Description | Status |
|-------|-------------|--------|
| 1 | Foundation (Flask, logging, DB, tests) | ✅ Complete |
| 2 | Sync engine (PPTX → SQLite + embeddings) | ✅ Complete |
| 3 | Case study library (browse, filter, search) | ✅ Complete |
| 4 | RFP upload + structured brief preview | ✅ Complete |
| 5 | Matching engine (embeddings + Claude) | ✅ Complete |
| 6 | Polish (export, user manual) | ⏳ Planned |

---

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite (dev), PostgreSQL (planned for production)
- **LLM:** Anthropic Claude Sonnet (matching, brief generation), Claude Haiku (engagement type fallback)
- **Embeddings:** OpenAI text-embedding-3-small
- **Document parsing:** pdfplumber, python-docx, python-pptx
- **Testing:** pytest (129 tests)
