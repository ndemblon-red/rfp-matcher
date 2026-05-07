"""
RFP Matcher eval suite.

Usage:
    python evals/run_evals.py

Requires:
  - ANTHROPIC_API_KEY in .env (always)
  - OPENAI_API_KEY in .env (for embedding-based pre-selection; falls back without it)
  - A populated database (run /sync first so case studies exist)
  - evals/fixtures/eval_fixture_good_match.pdf  (or .txt)
  - evals/fixtures/eval_fixture_no_match.pdf    (or .txt)

Category 1 — Off-topic guard:   no AI judge; checks that nonsense inputs return 0 matches above 25
Category 2 — Brief quality:     AI judge scores the generated brief 1–5; PASS >= 3
Category 3 — Match quality:     score thresholds + AI judge on the top result from the good-match fixture
"""

import json
import pathlib
import sys

# ── Path setup ────────────────────────────────────────────────────────────────

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import analysis as analysis_mod
from db import get_case_studies_for_scoring

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Fixtures: (filename_stem, display_label)
FIXTURE_GOOD_MATCH = ("eval_fixture_good_match", "good match")
FIXTURE_NO_MATCH   = ("eval_fixture_no_match",   "no match")

# Threshold: documents longer than this are too large to send raw to Claude
_LARGE_DOC_CHARS = 5_000

# ── Model rates (USD per token) ───────────────────────────────────────────────
_SONNET_IN  = 3.00  / 1_000_000
_SONNET_OUT = 15.00 / 1_000_000

# ── Token tracking ────────────────────────────────────────────────────────────

_tokens = {"input": 0, "output": 0}
_original_call_claude = analysis_mod._call_claude


def _tracked_call_claude(system, user, **kwargs):
    result = _original_call_claude(system, user, **kwargs)
    _tokens["input"]  += result.get("input_tokens", 0)
    _tokens["output"] += result.get("output_tokens", 0)
    return result


analysis_mod._call_claude = _tracked_call_claude


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_fixture(filename_stem):
    """Return extracted text for a fixture, trying .pdf then .txt."""
    from extraction import extract_text
    for ext in (".pdf", ".txt"):
        path = FIXTURES / (filename_stem + ext)
        if path.exists():
            if ext == ".txt":
                return path.read_text(encoding="utf-8")
            return extract_text(str(path))
    return None


def _prepare_rfp_for_matching(rfp_text):
    """Return (rfp_text_for_claude, brief) ready to pass to match_case_studies.

    For large documents, generates a brief first and uses its compact representation
    as the RFP text — matching how the real app handles file uploads. This avoids
    sending procurement boilerplate and tables of contents to the matching engine.
    For short inputs, returns the raw text and lets match_case_studies handle briefing.
    """
    if len(rfp_text) <= _LARGE_DOC_CHARS:
        return rfp_text, None

    brief = analysis_mod.generate_brief(rfp_text[:8000])
    compact = analysis_mod._build_rfp_embedding_text(brief)
    return compact, brief


def _ai_judge(prompt, max_tokens=400):
    """Call Claude Sonnet as judge; return the raw text and track tokens."""
    result = _original_call_claude(
        system=(
            "You are an impartial evaluator for an AI-powered RFP matching tool. "
            "Answer concisely and follow the format requested exactly."
        ),
        user=prompt,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    _tokens["input"]  += result.get("input_tokens", 0)
    _tokens["output"] += result.get("output_tokens", 0)
    return result["text"]


def _result_row(name, passed, detail):
    return (name, "PASS" if passed else "FAIL", detail, passed)


# ── Eval categories ───────────────────────────────────────────────────────────

def eval_off_topic(case_studies):
    """
    Category 1: Off-topic guard.
    No AI judge — checks that nonsense inputs return 0 matches above 25.
    """
    inputs = [
        ("capital of France",   "what is the capital of France"),
        ("poem about autumn",   "write me a poem about autumn"),
        ("CEO of OpenAI",       "who is the CEO of OpenAI"),
        ("2+2",                 "what's 2+2"),
        ("flight to Oslo",      "book me a flight to Oslo"),
    ]

    rows = []
    for label, text in inputs:
        results = analysis_mod.match_case_studies(text, case_studies)
        above = [r for r in results if r.get("score", 0) > 25]
        passed = len(above) == 0
        detail = "0 results" if passed else f"{len(above)} result(s) above 25 — guard failed"
        rows.append(_result_row(f"Off-topic: {label}", passed, detail))
    return rows


def eval_brief_quality(rfp_texts):
    """
    Category 2: Brief quality (AI-as-judge).
    Calls generate_brief() with up to 8000 chars — enough to cover substantive sections
    without sending procurement boilerplate. Judge scores 1–5; PASS >= 3.
    """
    rows = []
    for label, rfp_text in rfp_texts:
        brief = analysis_mod.generate_brief(rfp_text[:8000])

        judge_prompt = f"""You are evaluating an AI-generated RFP brief.

Original RFP (up to 8000 chars):
{rfp_text[:8000]}

Generated brief:
{json.dumps(brief, indent=2)}

Does this brief accurately capture the objective and key requirements of the RFP?
Reply in exactly this format:
Score: <integer 1-5>
Reason: <one sentence>"""

        response = _ai_judge(judge_prompt, max_tokens=150)

        score = None
        reason = response.strip()
        for line in response.splitlines():
            if line.lower().startswith("score:"):
                try:
                    score = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            if line.lower().startswith("reason:"):
                reason = line.split(":", 1)[1].strip()

        if score is None:
            passed, detail = False, f"could not parse score — raw: {response[:80]}"
        else:
            passed, detail = score >= 3, f"{score}/5 — {reason}"

        rows.append(_result_row(f"Brief quality: {label}", passed, detail))
    return rows


def eval_match_quality(rfp_texts, case_studies):
    """
    Category 3: Match quality.
    good match:  PASS if >= 2 results score above 50.
    no match:    PASS if 0 results score above 40.
    good match top result: AI judge PASS if yes.

    For large documents, generates a brief first and uses its compact representation
    as the RFP input — matching the real upload pipeline exactly.
    """
    rows = []
    good_match_brief   = None
    good_match_results = []

    for label, rfp_text in rfp_texts:
        rfp_for_claude, brief = _prepare_rfp_for_matching(rfp_text)
        caps = brief.get("capabilities_needed", []) if brief else []
        results = analysis_mod.match_case_studies(
            rfp_for_claude, case_studies,
            brief_capabilities=caps, brief=brief,
        )

        if label == "good match":
            good_match_brief   = brief
            good_match_results = results
            above_50 = [r for r in results if r.get("score", 0) > 50]
            passed = len(above_50) >= 2
            detail = f"{len(above_50)} result(s) > 50"
            rows.append(_result_row("Match quality: good match results", passed, detail))

        elif label == "no match":
            above_40 = [r for r in results if r.get("score", 0) > 40]
            passed = len(above_40) == 0
            detail = "0 results > 40" if passed else f"{len(above_40)} result(s) > 40 — expected none"
            rows.append(_result_row("Match quality: no match guard", passed, detail))

    # AI judge on the top good-match result
    if good_match_results:
        top = good_match_results[0]
        objective  = good_match_brief.get("objective", "") if good_match_brief else "(unavailable)"
        challenges = "; ".join(good_match_brief.get("challenges", [])) if good_match_brief else ""

        judge_prompt = f"""You are evaluating an AI case-study matching tool for a management consulting firm.

RFP objective: {objective}
RFP challenges: {challenges}

Top matched case study:
  Title: {top['title']}
  Industry: {top.get('industry_full') or 'unknown'}
  Engagement type: {top.get('engagement_type') or 'unknown'}
  Match score: {top['score']}
  Explanation: {top.get('explanation', '')}

Is this case study genuinely relevant to the RFP above?
Reply in exactly this format:
Answer: yes or no
Reason: <one sentence>"""

        response = _ai_judge(judge_prompt, max_tokens=120)

        answer = None
        reason = response.strip()
        for line in response.splitlines():
            if line.lower().startswith("answer:"):
                answer = line.split(":", 1)[1].strip().lower()
            if line.lower().startswith("reason:"):
                reason = line.split(":", 1)[1].strip()

        if answer is None:
            passed, detail = False, f"could not parse answer — raw: {response[:80]}"
        else:
            passed = answer.startswith("yes")
            detail = f"{answer} — {reason}"

        rows.append(_result_row("Match quality: good match top result", passed, detail))
    else:
        rows.append(_result_row("Match quality: good match top result", False,
                                "no results returned — cannot judge"))

    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\nRFP Matcher — Eval Suite")
    print("=" * 60)

    # ── Load case studies ─────────────────────────────────────────────────────
    case_studies = get_case_studies_for_scoring()
    if not case_studies:
        print("\nWARNING: database has no case studies. Run /sync first.")
        print("Off-topic guard and match quality evals will be skipped.\n")

    # ── Load RFP fixtures ─────────────────────────────────────────────────────
    rfp_texts = []
    missing = []
    for stem, label in [FIXTURE_GOOD_MATCH, FIXTURE_NO_MATCH]:
        text = _load_fixture(stem)
        if text:
            rfp_texts.append((label, text))
            print(f"Loaded {stem}: {len(text.split()):,} words"
                  + (" (large — will use brief-based pipeline)" if len(text) > _LARGE_DOC_CHARS else ""))
        else:
            missing.append(stem)
            print(f"MISSING fixture: {stem}.pdf or {stem}.txt — brief/match evals will skip it")

    if missing:
        print(f"\nDrop files into: {FIXTURES}\n")

    print()

    # ── Run categories ────────────────────────────────────────────────────────
    all_rows = []

    # Category 1
    if case_studies:
        print("Running Category 1: Off-topic guard...")
        all_rows.extend(eval_off_topic(case_studies))
    else:
        for label in ["capital of France", "poem about autumn", "CEO of OpenAI", "2+2", "flight to Oslo"]:
            all_rows.append(_result_row(f"Off-topic: {label}", False, "SKIPPED — no case studies in DB"))

    # Category 2
    if rfp_texts:
        print("Running Category 2: Brief quality (AI judge)...")
        all_rows.extend(eval_brief_quality(rfp_texts))
    else:
        for label in [FIXTURE_GOOD_MATCH[1], FIXTURE_NO_MATCH[1]]:
            all_rows.append(_result_row(f"Brief quality: {label}", False, "SKIPPED — fixture missing"))

    # Category 3
    if rfp_texts and case_studies:
        print("Running Category 3: Match quality...")
        all_rows.extend(eval_match_quality(rfp_texts, case_studies))
    else:
        reason = "SKIPPED — " + ("fixture missing" if not rfp_texts else "no case studies in DB")
        for label in ["good match results", "no match guard", "good match top result"]:
            all_rows.append(_result_row(f"Match quality: {label}", False, reason))

    # ── Summary table ─────────────────────────────────────────────────────────
    col_name   = max(len(r[0]) for r in all_rows)
    col_detail = max(len(r[2]) for r in all_rows)
    sep = "─" * (col_name + 8 + col_detail)

    print()
    print(f"{'Eval':<{col_name}}  {'Result':<6}  {'Score/Detail'}")
    print(sep)
    passed_count = 0
    for name, status, detail, passed in all_rows:
        print(f"{name:<{col_name}}  {status:<6}  {detail}")
        if passed:
            passed_count += 1
    print(sep)
    print(f"Total: {passed_count}/{len(all_rows)} passed")

    # ── Cost estimate ─────────────────────────────────────────────────────────
    cost = _tokens["input"] * _SONNET_IN + _tokens["output"] * _SONNET_OUT
    print()
    print(f"API usage (Sonnet):  {_tokens['input']:,} input tokens, {_tokens['output']:,} output tokens")
    print(f"Estimated cost:      ${cost:.4f}")
    print()

    return 0 if passed_count == len(all_rows) else 1


if __name__ == "__main__":
    sys.exit(main())
