# RFP Matcher Build Retrospective
*April 27-28, 2026*

---

## What We Built

An internal Flask web app that syncs ADL Catalyst case studies from a live PPTX file into a searchable SQLite database, with a library view and the foundations of an RFP matching engine. The app reads directly from a OneDrive-synced SharePoint folder so data is always live.

---

## The Journey: Key Decisions & U-Turns

### 1. The Slide Number Comedy
**What happened:** Early on, slide number was proposed as too brittle to use as a matching key — "every time someone adds a case study alphabetically, all the numbers shift." We spent considerable time designing a fuzzy-matching approach using client name + project title instead.

**The U-turn:** After days of debugging failed fuzzy matches, duplicate titles, and mismatched data, we went full circle. Slide number is now the **primary key** in the database. It works because: (a) the sync runs after every update so numbers stay current, and (b) the content hash detects shifts and updates slide numbers without re-inferring metadata.

**Lesson:** Sometimes the "brittle" solution is actually the most pragmatic one. Don't over-engineer before you've tried the simple approach.

---

### 2. Excel as Source of Truth → Dropped Entirely
**What happened:** The project started with a plan to use the Excel inventory file as the metadata source, matching it to PPTX slides for content. This seemed sensible — the Excel already had industry, AI type, client, and slide numbers all neatly organised.

**The problems:** Slide number mismatches, duplicate project titles across different clients, "NOT IN DB" flags from a previous exercise, client names that didn't match between files, fuzzy matching failures at scale.

**The U-turn:** Dropped the Excel completely. The PPTX is the single source of truth. The Excel remains useful as a portfolio management tool for the team, but plays no role in the RFP matcher.

**Lesson:** When two data sources are supposed to represent the same thing, one will always drift from the other. Pick one source of truth and commit to it.

---

### 3. AI Inference During Sync → Local Keyword Mapping
**What happened:** The sync script was calling the Claude API for every slide to infer industry and AI type. This seemed like the right approach — let the AI read the content and map to the standard lists.

**The problems:** 
- Hit API rate limits (429 errors) mid-sync
- Ran out of API credits entirely, leaving 26 case studies unprocessed
- Slow (1-2 seconds per slide × 99 slides = 3+ minutes)
- Expensive for something that runs regularly

**The U-turn:** Replaced all API calls in the sync with a local keyword lookup table. The industry label is already in brackets in the slide heading (e.g. "COMMODITY PRICE FORECASTING **(PETROCHEMICAL)**") — just map that to the standard list. AI type is inferred from keywords in the slide text.

**Lesson:** Don't use a sledgehammer where a screwdriver will do. The sync is now free, instant, and reliable. Save the API for where it genuinely adds value — the matching step.

---

### 4. Metadata Is Less Important Than Content
**What happened:** Significant time was spent trying to accurately capture client name, industry, AI type for every case study. This seemed important for filtering and matching.

**The realisation:** For RFP matching, what matters is the actual slide content — the challenge description, approach, and results. An RFP describes a business problem, and the best match is the case study whose challenge most closely mirrors that problem. Industry and AI type are useful for filtering in the library view, but they're secondary signals for matching.

**Lesson:** Match on content, not metadata. The metadata is a convenience layer, not the core capability.

---

### 5. Client Name Detection: A Rabbit Hole
**What happened:** Considerable time was spent trying to extract client names from slide logos using Claude vision. Various approaches were tried:
- Top-right quadrant crop
- Shape nearest to "REMOVE LOGO BEFORE USE" box
- Shapes below the "REMOVE LOGO BEFORE USE" box
- Text shapes vs image shapes

**The U-turn:** Dropped client name from the database entirely. The user will see the client when they look at the actual slide. This solved the problem completely and immediately.

**Lesson:** If a piece of data is hard to extract reliably and isn't actually needed for the core function, don't extract it. YAGNI (You Aren't Gonna Need It).

---

### 6. Lost Build Plan Due to Context Window Compaction
**What happened:** Claude Code ran a long session, the context window filled up, and the build plan generated at the start of the session was compacted/lost. Claude Code subsequently didn't know what had been planned or what slice came next.

**The fix:** Created a `PLAN.md` file in the project root that persists the build plan to disk. Future sessions start with "read PLAN.md".

**Lesson:** Any plan that only exists in an AI's context window will eventually be lost. Always write important decisions and plans to files. This is actually a gap in the skill methodology — Phase 4 should mandate creating a `PLAN.md` before writing any code.

---

### 7. Claude Code vs Chat Sessions
**What happened:** Previous projects (healthreg-rag, Catalyst intake) were built in Claude.ai chat sessions. This project switched to Claude Code.

**Why the switch made sense:** The app needs to interact with local files (OneDrive-synced PPTX), run scripts, and maintain project context across sessions. Claude Code can see the file system directly.

**Friction encountered:** 
- `/mnt/skills` path doesn't resolve on Windows — skill files had to be manually downloaded and placed locally
- Context window compaction still happens in Claude Code
- Some Windows-specific issues (PowerShell vs bash, `wc` not available, etc.)

**Lesson:** Claude Code is the right tool for file-system-dependent projects, but the skill files need to be copied locally first. Build a habit of doing this at the start of every new project.

---

## 8. Working From Live Documents — A Journey in Itself

**The requirement:** The app needed to always read the live PPTX and Excel from SharePoint, not stale local copies. This seemed straightforward but turned into one of the most friction-heavy parts of the build.

**Attempt 1 — Microsoft Graph API:** The "proper" enterprise solution. Rejected early because it requires Azure AD app registration and IT admin involvement. Too much overhead for a PoC.

**Attempt 2 — MCP Connector:** Checked if a SharePoint/OneDrive connector existed in Claude.ai's connector registry. Nothing available.

**Attempt 3 — OneDrive Sync (Option 3):** Settled on syncing the SharePoint folder to local machine via OneDrive. Simple, no admin required, files always live. This worked — but introduced a new problem.

**Problem: OneDrive Files On-Demand:** Even after setting "Always keep on this device", OneDrive periodically evicted files back to cloud-only status to save disk space. When the sync script tried to open the PPTX, it would fail because the file was a cloud placeholder, not a real local file.

**Attempt 4 — `attrib` command to trigger recall:** The sync script called `subprocess.run(["attrib", pptx_path])` before opening the file, which was supposed to trigger OneDrive to download it. Unreliable — sometimes worked, sometimes didn't.

**Attempt 5 — Retry loop with PermissionError handling:** Added 5 retries with 5-second delays to handle OneDrive locks. Helped with locking but didn't solve the cloud-only placeholder problem.

**Attempt 6 — `shutil.copy2` to a local temp file (final solution):** Instead of opening the OneDrive file directly, copy it to a local temp file first, then open the copy. OneDrive can do whatever it wants with the original — the sync always works from a guaranteed local copy. The temp file is deleted in a `finally` block. This is the solution that stuck.

**Lesson:** When working with cloud-synced files programmatically, never open them directly. Always copy to a local temp file first. The copy operation is the only point of contact with the cloud sync — once you have a local copy, everything else is predictable.

---

## Technical Decisions That Worked Well

- **OneDrive sync + shutil.copy2** for reading live files without locking issues
- **Content hash** for incremental syncs that survive slide number shifts
- **`UNIQUE(slide_num)`** as the DB key — simple, reliable, always correct after sync
- **Section divider detection** to automatically find the case studies range in the PPTX
- **Video variant deduplication** — `has_video` flag on base record instead of duplicate rows
- **Local keyword inference** for industry/AI type — free, fast, no API dependency

---

## Things Still To Do

- **Slice 5:** RFP matching engine (needs API credits)
  - Free text / keyword search input (UI built, logic pending)
  - Claude API matching against slide content
  - Top 3-5 results with explanation
  - Logo detection on matched results only (vision at query time, not sync time)
- **Slice 6:** Polish, export, user manual
- **Technical debt:** SQLite → PostgreSQL for production, auth consideration

---

## Stats

- **Sessions:** 2 days
- **Approach changes:** ~7 major pivots
- **API calls burned on sync (before local inference):** ~72 (then ran out of credits)
- **Final DB record count:** 99 case studies
- **Lines of code in app.py:** ~170 (well under blueprint threshold)
- **Tests passing:** 32+

---

## The Meta Lesson

> The best architecture emerges from constraints you discover during building, not from upfront design. The slide number was "too brittle" until it wasn't. The Excel was "the source of truth" until it wasn't. The AI inference was "necessary" until it wasn't. Each U-turn made the system simpler and more reliable than the original plan.
