# Session 3 Notes — Evals, Brief Quality & Matching Refinement
*May 2026*

---

## What We Did This Session

Three main threads: building the eval framework, iteratively improving brief quality through manual testing, and refining the matching engine based on real-world testing.

---

## 1. Eval Framework

### Design decisions
Decided against an eval platform — too complex for the use case. Instead built a simple Python script (`evals/run_evals.py`) that calls `generate_brief()` and `match_case_studies()` directly (no HTTP calls) and prints a pass/fail summary.

Three eval categories:
- **Off-topic guard** — 5 clearly off-topic inputs, assert 0 results above threshold or `is_relevant=false`
- **Brief quality** — AI-as-judge: send brief + original RFP to Claude, score 1-5, pass if ≥3
- **Match quality** — assert good match RFP returns ≥2 results above 50, no-match RFP returns 0 results above 40

### Fixture files
Two RFP fixtures stored as plain text in `evals/fixtures/` (in `.gitignore` — not committed):
- `eval_fixture_good_match.txt` — Back-office optimisation RFP for a multi-entity energy company (good match expected)
- `eval_fixture_no_match.txt` — Regulatory cost modelling tender for a national communications authority (no match expected)

Named without client references deliberately. The eval script uses `extraction.extract_text()` to read them — same pipeline as the real app, supports both `.pdf` and `.txt`.

### Off-topic guard improvement
Added `is_relevant` boolean to `generate_brief()` JSON response — Claude determines relevance as part of the same API call, no extra cost. If `is_relevant=false`, the app redirects back to `/match` with a targeted message rather than running the full matching pipeline.

---

## 2. Manual Brief Quality Testing

Ran iterative manual tests on both fixture RFPs, scoring briefs as AI-as-judge in Claude.

### Iteration history

**v1 (original prompt):** Generic, vague. The no-match RFP brief scored 3/5 — missed technology scope, regulatory flexibility, IT delivery dimension entirely.

**v2 (specific improvements):** Added concrete principles for objective, challenges, capabilities. No-match RFP improved to 4/5 but technology scope error persisted (listed out-of-scope technologies as in-scope when they're explicitly excluded).

**v3 (COMMON ERRORS TO AVOID section):** Added targeted negative constraints. Initially too RFP-specific. Generalised to six universal extraction failure modes.

**v4 (generalised + two new additions):** Added language/location requirements and experience quality distinctions as generalizable categories. Good-match RFP brief scored 4.5/5. No-match RFP would score ~4/5 with remaining gaps being minor.

### Key lessons from manual testing
- Claude consistently picks up background context and includes it as scope — explicit "scope creep" guard needed
- Multi-scenario architectural requirements get buried in context rather than flagged as primary design drivers
- Technical delivery roles get collapsed into domain expertise ("AI expertise" instead of "hands-on AI implementation with references")
- Language requirements are a hard go/no-go filter and were missing from every brief until explicitly instructed

### Final prompt structure
Split into two constants for maintainability:
- `_SYSTEM_BRIEF_INSTRUCTIONS` — analytical guidance (how to think)
- `_SYSTEM_BRIEF_FORMAT` — JSON schema (how to structure output)

Combined as `_SYSTEM_BRIEF = _SYSTEM_BRIEF_INSTRUCTIONS + "\n\n" + _SYSTEM_BRIEF_FORMAT`

---

## 3. Matching Engine Refinements

### False positive problem (no-match RFP)
A highly specialised regulatory cost modelling tender was returning high scores (75+) against unrelated case studies like "Digital Transformation Strategy (Finance)". Root cause: keyword overlap on "cost modelling" and "benchmarking" without understanding the domain difference.

Fix: switched from keyword pre-scoring to OpenAI `text-embedding-3-small` embeddings. The Nkom tender now correctly returns no strong matches because its vector is far from any case study in the library.

### Result card improvements
Each result card now shows:
- **Why it matches** — similarities (1-2 sentences)
- **Key difference** — one sentence on what's fundamentally different
- Colour-coded score badge (green/amber/grey)
- Capability pills (Claude-matched, not keyword-matched)
- No results shown below score threshold of 25

### Engagement type expansion
Renamed `ai_type` → `engagement_type`. Expanded categories to cover all project types including Cybersecurity, AI Strategy, and Digital Strategy — so every case study gets a category, not just AI projects.

---

## Technical Notes

- `generate_brief()` now has `is_relevant` boolean — no extra API call
- `max_tokens` increased to 1024 for brief generation (512 was truncating long RFPs)
- Fixture files are in `.gitignore` — no client data ever committed to GitHub
- Eval script at `evals/run_evals.py` — run with `python evals/run_evals.py`

---

## What's Still To Do

- Run the automated eval suite end-to-end and record baseline scores
- Test pure-Claude matching (no embeddings) and compare eval scores — **important note: the brief quality improvements made in this session will likely improve match quality regardless of the matching approach used. Before comparing embedding vs pure-Claude approaches, establish a baseline eval score with the current embedding approach using the improved brief. This ensures the comparison isolates the matching approach, not brief quality.**
- CSRF protection (Flask-WTF)
- Export results as DOCX
- User manual
