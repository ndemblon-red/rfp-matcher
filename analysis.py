import os
import json
import re
import logging

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _call_claude(system, user, max_tokens=512, temperature=0.2):
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text
        return {
            "text": text,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "truncated": response.stop_reason == "max_tokens",
        }
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Could not connect to Claude API: {e}") from e


def _safe_parse_json(text, context="unknown"):
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    repaired = cleaned
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")

    if open_braces > 0 or open_brackets > 0:
        last_comma = repaired.rfind(",")
        if last_comma > 0:
            repaired = repaired[:last_comma]

    repaired += "]" * open_brackets + "}" * open_braces

    try:
        result = json.loads(repaired)
        logger.warning("[%s] Repaired truncated JSON (%d braces, %d brackets)", context, open_braces, open_brackets)
        return result
    except json.JSONDecodeError as e:
        logger.error("[%s] Failed to parse JSON even after repair: %s", context, e)
        logger.error("[%s] First 500 chars: %s", context, cleaned[:500])
        raise ValueError(f"AI response was not valid JSON in {context}") from e


# ── RFP brief generation ─────────────────────────────────────────────────────

_SYSTEM_BRIEF = """You are an RFP analyst for a management consulting firm.
Analyse the input — which may be a full RFP document or a short business description — and produce a structured brief.

Respond with ONLY valid JSON. No markdown, no preamble:
{
  "objective": "One sentence stating the client's core goal or business problem.",
  "challenges": ["2 to 4 short phrases — the key challenges or pain points driving this initiative"],
  "capabilities_needed": ["3 to 6 short, specific capability tags, e.g. 'predictive analytics', 'process automation', 'change management', 'real-time monitoring'"],
  "context": {
    "industry": "Client industry or sector — empty string if not mentioned",
    "scale": "Scale or scope of the engagement — empty string if not mentioned",
    "constraints": "Notable constraints or requirements — empty string if not mentioned"
  }
}

Rules:
- capabilities_needed tags must be 1–3 words each, specific and scannable
- If the input is very short, infer reasonable values from what is available
- Always return valid JSON — never refuse or add explanation"""


def generate_brief(rfp_text):
    """Generate a structured brief from RFP text or a short problem description.

    Returns {objective, challenges, capabilities_needed, context}.
    Raises RuntimeError on API failure, ValueError if response is not valid JSON.
    """
    result = _call_claude(
        system=_SYSTEM_BRIEF,
        user=rfp_text[:8000],
        max_tokens=600,
        temperature=0.2,
    )
    if result["truncated"]:
        logger.warning("generate_brief: response truncated — JSON may be incomplete")
    return _safe_parse_json(result["text"], "generate_brief")


# ── Section extraction ────────────────────────────────────────────────────────

# Matches a section header and lazily captures everything up to the next header or end of string.
_SECTION_RE = re.compile(
    r'\b(Challenge|Approach|Results?|Outcomes?)\b'
    r'[ \t]*:?[ \t]*\n?'
    r'(.*?)'
    r'(?=\s*\b(?:Challenge|Approach|Results?|Outcomes?)\b|\Z)',
    re.IGNORECASE | re.DOTALL,
)

_LABEL_MAP = {
    "challenge": "challenge",
    "approach":  "approach",
    "result":    "results",
    "results":   "results",
    "outcome":   "results",
    "outcomes":  "results",
}


def _extract_sections(slide_content):
    """Extract Challenge, Approach, and Results blocks from slide text.

    Returns a dict with keys from {'challenge', 'approach', 'results'}.
    Missing sections are omitted; first occurrence of each label wins.
    """
    out = {}
    for m in _SECTION_RE.finditer(slide_content):
        label = _LABEL_MAP.get(m.group(1).lower())
        if label and label not in out:
            body = m.group(2).strip()
            if body:
                out[label] = body
    return out


# ── Single-call matching ──────────────────────────────────────────────────────

_SYSTEM_MATCH = """You are a case study matching assistant for a management consulting firm.

You will receive a client RFP or business problem description, and a set of consulting case studies.
Each case study contains only the business challenge, approach, and outcomes — no industry or sector labels.

Your task: identify the most relevant case studies (up to 5) based purely on similarity of business problem, approach, and outcomes to the RFP. Only return case studies that score above 25.

Scoring rubric — be strict:
- 70–100: Genuinely strong match. The case study addresses a substantially similar business challenge and approach. A consultant could directly cite it as a precedent.
- 40–69: Partial match. Meaningful overlap in problem type or approach, but not both.
- 26–39: Weak match. Only superficial or coincidental similarity.
- 25 and below: Do not include in the response.

A genuine match requires the core business problem — what the client is trying to achieve and why — to be substantially similar. Generic overlap in terms like 'cost', 'analysis', 'strategy', or 'transformation' alone is NOT sufficient for a score above 30. If you find yourself citing only generic business terms as the reason for similarity, score below 30.

Critical rules:
- Ignore industry and sector entirely. A retail loyalty programme can match a telco retention strategy if the underlying business problem and approach are the same.
- Match on the nature of the problem, the analytical or strategic approach, and the type of outcome — not on surface-level keywords or industry labels.
- Do not penalise a case study for being in a different industry or having a different engagement type.
- For each case study you consider, you must briefly state the key difference between the RFP and the case study before assigning a score. This prevents surface-level keyword matching from inflating scores.

For each qualifying match, write a 2–3 sentence explanation. Begin with "Key difference: [one sentence on the most important way this case study differs from the RFP]." Then add 1–2 sentences on why it is still a useful precedent despite that difference.

If a "Capabilities needed" list is provided, also return matched_caps: the subset of those capability tags that are genuinely addressed by the case study, judged by meaning not exact wording. Return an empty array if none apply or no list was provided.

Return ONLY case studies scoring above 25, up to a maximum of 5, sorted by score descending. If fewer than 5 qualify, return only those that do. If none qualify, return an empty array [].

Respond with ONLY a valid JSON array. No markdown, no preamble:
[{"id": <integer>, "score": <integer 26–100>, "explanation": "<Key difference: ...> <1–2 sentences>", "matched_caps": [<string>, ...]}, ...]"""


def match_case_studies(rfp_text, case_studies, brief_capabilities=None):
    """Match RFP text against all case studies in a single Claude API call.

    Sends extracted Challenge/Approach/Results sections for each case study;
    falls back to raw slide content when no structured sections are found.
    Returns up to 5 dicts: {id, title, industry_full, engagement_type, has_video, score, explanation, matched_caps}.
    Raises RuntimeError on API failure, ValueError if response is not valid JSON.
    """
    if not case_studies:
        return []

    capabilities = brief_capabilities or []

    cs_payload = []
    for cs in case_studies:
        sections = _extract_sections(cs.get("slide_content") or "")
        entry = {"id": cs["id"], "title": cs["title"]}
        if sections:
            entry.update(sections)
        else:
            raw = (cs.get("slide_content") or "").strip()
            if raw:
                entry["content"] = raw
        cs_payload.append(entry)

    user_parts = [f"Client RFP / Problem:\n{rfp_text}"]
    if capabilities:
        user_parts.append(f"Capabilities needed:\n{json.dumps(capabilities)}")
    user_parts.append(f"Case Studies:\n{json.dumps(cs_payload, indent=2)}")
    user_msg = "\n\n---\n\n".join(user_parts)

    result = _call_claude(
        system=_SYSTEM_MATCH,
        user=user_msg,
        max_tokens=2000,
        temperature=0.1,
    )
    if result["truncated"]:
        logger.warning("match_case_studies: response truncated — JSON may be incomplete")

    scored = _safe_parse_json(result["text"], "match_case_studies")
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    above_threshold = [item for item in scored if item.get("score", 0) > 25]

    cs_by_id = {cs["id"]: cs for cs in case_studies}
    results = []
    for item in above_threshold[:5]:
        cs = cs_by_id.get(item["id"], {})
        results.append({
            "id": item["id"],
            "title": cs.get("title", ""),
            "industry_full": cs.get("industry_full"),
            "engagement_type": cs.get("engagement_type"),
            "has_video": cs.get("has_video", 0),
            "score": item.get("score", 0),
            "explanation": item.get("explanation", ""),
            "matched_caps": item.get("matched_caps") or [],
        })

    return results
