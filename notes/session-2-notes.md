# Session 2 Notes — Matching Engine & Architecture Evolution
*April 2026*

---

## What We Built This Session

The matching engine (Slice 5) went from skeleton to a working two-step semantic pipeline. We also significantly evolved the architecture based on real-world testing — including one major architectural pivot that made the tool fundamentally more honest.

---

## Key Changes

### Matching Engine — From Keywords to Embeddings

**Where we started:** A basic two-step approach — keyword pre-scoring to get top 10 candidates, then Claude re-scoring and explaining those 10.

**What went wrong:** Testing with a highly specialised regulatory cost modelling tender revealed the system was returning high scores (75+) for completely unrelated case studies. The reason: both documents shared terms like "cost modelling" and "benchmarking" — but in completely different senses. Claude was finding surface-level keyword overlap and dressing it up as a match.

**The diagnosis:** Keyword pre-scoring was the problem. It was filtering the candidates Claude saw, ensuring Claude only reasoned about cases that already had superficial keyword overlap. Cases with genuinely similar *business problems* but different vocabulary were never surfaced.

**The fix — embeddings:** Replaced keyword pre-scoring entirely with OpenAI `text-embedding-3-small` semantic vectors. Now:

1. At sync time, each case study's Challenge/Approach/Results sections are embedded and stored as a BLOB in SQLite
2. At query time, the RFP brief (objective + challenges + capabilities) is embedded
3. Cosine similarity finds the top 10 genuinely semantically similar cases
4. Claude does deep reasoning only on those 10 — producing similarities, differences, score, and matched capability pills

The regulatory tender now correctly returns no strong matches, because no case study has a similar vector. "Regulatory network cost modelling" and "IT cost review during a pandemic" are far apart in embedding space even if they share vocabulary.

**Lesson:** Embeddings fix the false positive problem at the root. Prompt engineering guardrails are treating symptoms; embeddings fix the cause.

---

### Structured Brief Preview

The match flow now has a genuinely useful intermediate step. When a user uploads an RFP or types a description, Claude generates a structured brief before matching:

- **Objective** — one sentence
- **Challenges** — 2-4 bullets  
- **Capabilities needed** — 3-6 tags (these become the capability pills shown on results)
- **Context** — industry, scale, constraints

The user reviews this before triggering matching. This lets them catch misunderstandings before wasting a match API call. It also makes the tool more transparent.

---

### Result Cards — Similarities & Differences

Each result card now shows:
- **Why it matches** — 1-2 sentences on genuine overlap
- **Key difference** — 1 sentence on what's fundamentally different
- **Score badge** — colour coded green/amber/grey by strength
- **Capability pills** — which brief capabilities the case study addresses (Claude-matched, not keyword-matched)

The "key difference" field is important — it actively discourages weak matches by making the gap visible to the user.

---

### Engagement Type (formerly AI Type)

Renamed `ai_type` to `engagement_type` and expanded the category list to cover all project types, not just AI projects:

- Generative AI, Machine Learning, Computer Vision, NLP, Data & Analytics (AI categories)
- Software & Platform, AI Strategy, Digital Strategy, Cybersecurity (non-AI categories)

Projects like "Cyber Security Audit" and "IT Operating Model" now get categorised correctly instead of being left blank. Claude API is used as a fallback for cases the keyword lookup can't categorise — called once per slide, result cached permanently.

---

### GitHub & Portfolio Setup

- Public repo created for portfolio visibility
- README written with problem statement, architecture diagram, key technical decisions
- Architecture Decision Records written (7 ADRs covering all major decisions)
- Retrospective notes saved to `notes/` folder
- PLAN.md created and kept updated as source of truth for build state

---

## Architecture Diagram (Updated)

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
  │ • Claude Haiku fallback for          │
  │   unclassifiable cases               │
  │ • Content hash → incremental syncs   │
  │ • OpenAI embeddings stored in DB     │
  └──────────────┬───────────────────────┘
                 │
                 ▼
          SQLite Database
          (slide_num PK, content,
           sections, embeddings BLOB)
                 │
        ┌────────┴─────────┐
        ▼                  ▼
  Library View       Matching Engine (analysis.py)
  /library           ┌──────────────────────────────┐
                     │ Input: PDF/DOCX upload        │
                     │        or free-text query     │
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
                     │ → max 5 results               │
                     └──────────────────────────────┘
```

---

## Stats

- **Tests passing:** 129
- **Case studies in DB:** 99
- **Lines of code in app.py:** 308 (at blueprint threshold — watch this)
- **Commits this session:** 6
- **Major architectural pivots:** 1 (keyword pre-scoring → embeddings)
