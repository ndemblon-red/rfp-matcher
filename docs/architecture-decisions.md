# Architecture Decision Records

This document captures the key architectural decisions made during the design and build of the RFP Matcher, including the context, options considered, and rationale. Updated as the project evolves.

---

## ADR-001: Single Source of Truth — PPTX Only

**Date:** April 2026
**Status:** Accepted

### Context
The case study library exists in two places: a PowerPoint deck (the primary presentation file) and an Excel spreadsheet (a metadata inventory with industry, AI type, slide numbers, etc.). The initial plan was to use both — the Excel for metadata and the PPTX for slide content.

### Decision
Use the PPTX as the sole data source. The Excel is not read by the application.

### Alternatives Considered
- **Excel + PPTX join:** Match rows by slide number or fuzzy title match. Rejected after extensive testing — slide numbers drift when new slides are inserted alphabetically, and title strings are inconsistently formatted between the two files, causing frequent match failures.
- **Excel only:** Rejected — the Excel doesn't contain full slide text, only metadata fields.

### Consequences
- All metadata (industry, AI type) must be inferred from slide content rather than read from a pre-populated spreadsheet
- The Excel remains useful as a team management tool (gap analysis, portfolio view) but has no role in the application
- Sync logic is simpler — one file, one parsing pass, no joins

---

## ADR-002: Slide Number as Primary Key

**Date:** April 2026
**Status:** Accepted

### Context
Each case study record in the database needs a stable unique identifier to support upserts on incremental syncs. Options considered were: slide number, client + title composite, or a content hash.

### Decision
Use `slide_num` (1-indexed position in the PPTX) as the primary key, combined with a content hash for change detection.

### Alternatives Considered
- **Client + title composite:** Rejected — client names are not reliably extractable from slides (logos only, no text), and duplicate project titles exist across different clients.
- **Content hash only:** Rejected as a primary key — hash changes whenever slide content is edited, breaking the stable identity needed for incremental updates.
- **Title only:** Rejected — multiple slides share the same project title (e.g. two clients both had "Digital Transformation Strategy").

### How Slide Number Shifts Are Handled
New case studies are inserted alphabetically, shifting all subsequent slide numbers. The sync handles this via content hash: if a hash already exists in the DB, the record's slide number is updated without re-processing the content. This keeps slide numbers accurate after every sync at zero additional cost.

### Consequences
- Slide numbers must be kept current — a full re-sync after any PPTX restructuring is recommended
- Slide numbers in the DB are always accurate immediately after a sync runs

---

## ADR-003: No API Calls During Sync

**Date:** April 2026
**Status:** Accepted

### Context
The sync script processes ~100 slides on each run. An early implementation called the Claude API for each slide to infer industry and AI type. This caused rate limit errors (HTTP 429), exhausted API credits mid-sync, and made each sync take 3+ minutes.

### Decision
Replace all API calls in the sync with a local keyword lookup table. The Claude API is only called during the matching step.

### How It Works
- **Industry:** The slide heading follows the pattern `CASE STUDIES | PROJECT NAME (INDUSTRY)`. The text in brackets is extracted and matched against a keyword lookup table (e.g. `"petrochemical"` → `"Chemicals"`). If no bracket match is found, the full slide text is scanned.
- **AI type:** The full slide text is scanned for keywords (e.g. `"forecasting"` → `"Machine Learning"`, `"llm"` → `"Generative AI"`).

### Consequences
- Sync is free, runs in under 30 seconds, and has no external dependencies
- Inference accuracy depends on keyword coverage — edge cases may be miscategorised
- The lookup tables must be maintained as new project types emerge
- Industry and AI type are useful for library filtering but are secondary signals for matching — the matching engine scores against full slide text, not metadata fields

---

## ADR-004: Live Files via OneDrive Sync + shutil.copy2

**Date:** April 2026
**Status:** Accepted

### Context
The PPTX lives in a SharePoint folder shared by the team. The app needs to always read the latest version — not a stale local copy. Several approaches were evaluated.

### Decision
Sync the SharePoint folder to the local machine via OneDrive. Before opening the file, copy it to a local temp file using `shutil.copy2`, then open the copy.

### Alternatives Considered and Rejected

| Approach | Reason Rejected |
|----------|----------------|
| Microsoft Graph API | Requires Azure AD app registration and IT admin involvement — too much overhead for a PoC |
| MCP Connector | No SharePoint/OneDrive connector available at time of build |
| Open OneDrive file directly | OneDrive's Files On-Demand feature periodically evicts files to cloud-only status, causing `PermissionError` when the app tries to open them. Retry loops and `attrib` triggers were unreliable |
| Disable Files On-Demand | Would work but changes system-wide OneDrive behaviour — not appropriate as a code-level fix |

### How It Works
```python
shutil.copy2(pptx_path, _TEMP_PPTX)   # copy from OneDrive path
prs = Presentation(_TEMP_PPTX)         # open the local copy
```
The temp file is deleted in a `finally` block regardless of whether processing succeeds or fails.

### Consequences
- The copy step is the only point of contact with OneDrive — once copied, all processing is local and predictable
- A 5-attempt retry loop with 5-second delays handles the rare case where OneDrive has a write lock on the file during active sync
- The temp file (`temp_casestudies.pptx`) is in `.gitignore`

---

## ADR-005: Match on Slide Content, Not Metadata

**Date:** April 2026
**Status:** Accepted

### Context
An early design assumed matching would work primarily against structured metadata fields (industry, AI type, keywords). This mirrors how most search systems work — index structured fields, match against them.

### Decision
The matching engine scores case studies against their full slide text (challenge, approach, results), not against metadata fields. Metadata (industry, AI type) is used as a secondary filter, not the primary match signal.

### Rationale
RFPs describe business problems in natural language. The best match is a case study whose challenge description most closely resembles the RFP — regardless of how it is tagged. Two projects tagged "Machine Learning / Healthcare" might be completely different in nature; two projects in different industries might describe essentially the same problem. Full-text semantic matching surfaces genuine similarity that metadata cannot.

### Consequences
- The matching engine requires the Claude API to understand semantic similarity — it cannot be done with keyword matching alone
- Metadata fields (industry, AI type) remain useful for library browsing and filtering, and as secondary signals to boost or explain matches
- The `slide_content` field in the DB stores the full concatenated text of every shape on the slide

---

## ADR-006: Video Variants as Flags, Not Separate Records

**Date:** April 2026
**Status:** Accepted

### Context
Several case studies exist in two versions in the PPTX: a standard slide and a "Version with Video" variant. The initial sync stored these as separate database records, resulting in duplicate matches in search results.

### Decision
Video variants are not stored as separate records. When a "Version with Video" slide is detected, the base case study record's `has_video` boolean is set to `true`. The variant slide itself is discarded.

### Detection Method
A slide is identified as a video variant if any text shape contains the phrase "Version with Video" (case-insensitive). This is more reliable than suffix-matching on the title (e.g. "with video" at end of string), which failed on titles where "video" appeared mid-string for unrelated reasons.

### Edge Case
If only the video variant exists (no base version in the PPTX), the variant is kept as the base record with `has_video = true`.

### Consequences
- No duplicate matches in RFP results
- The `has_video` flag is surfaced in the library view so users know a video version is available
- The video slide's content is not stored — if it contains materially different text from the base slide, that content is lost

---

## ADR-007: Defer Client Name Extraction

**Date:** April 2026
**Status:** Accepted

### Context
Client names on case study slides are displayed as logos, not text. Several approaches were attempted to extract them programmatically: full-slide vision, top-right quadrant crop, shape proximity to a "REMOVE LOGO BEFORE USE" placeholder, and plain-text shape detection.

### Decision
Client name is not stored in the database. It is deferred to query time: when the matching engine returns results, Claude vision is called on the matched slides only to identify the client logo. The result is cached in the DB to avoid repeat API calls.

### Rationale
- Batch logo extraction during sync was unreliable due to inconsistent logo placement across slides
- Client name is not needed for matching — the match is on slide content
- Running vision on 3–5 result slides at query time is fast and accurate
- Caching means each slide is only vision-processed once

### Consequences
- The `logo_name` column is added to the DB in Slice 5 (matching engine)
- First query for a given case study incurs one vision API call; subsequent queries use the cache
- If a client logo is updated in the PPTX, the cached name will be stale until manually cleared
