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


_SYSTEM_EXTRACT = """You are a case study matching assistant for a management consulting firm.
Your only task is to analyse RFP documents and business problem descriptions to extract structured matching signals.

Analyse the input and respond with ONLY a JSON object in one of these two forms:

If the input IS a business problem, RFP, or consulting opportunity:
{
    "off_topic": false,
    "industry_signals": ["string — industry or sector names, up to 5"],
    "problem_type": "string — one short phrase describing the core problem type",
    "capabilities_needed": ["string — AI or technology capabilities required, up to 5"],
    "keywords": ["string — 8 to 15 specific keywords relevant to the problem"]
}

If the input is NOT a business problem or RFP (e.g. personal questions, random text, code, jokes):
{
    "off_topic": true,
    "off_topic_reason": "string — one short sentence explaining why"
}

Rules:
- Be specific: prefer "predictive maintenance" over "AI", "retail banking" over "finance"
- Keywords must appear in or be strongly implied by the input text
- Respond with ONLY valid JSON. No markdown, no explanation."""


def extract_requirements(rfp_text):
    """Send RFP text to Claude and return structured requirements dict.

    Returns a dict with off_topic=True if the input is not a business problem.
    Raises RuntimeError on API failure, ValueError if the response is not valid JSON.
    """
    result = _call_claude(
        system=_SYSTEM_EXTRACT,
        user=rfp_text[:8000],
        max_tokens=512,
        temperature=0.2,
    )
    if result["truncated"]:
        logger.warning("extract_requirements: response truncated — JSON may be incomplete")
    return _safe_parse_json(result["text"], "extract_requirements")


def score_case_studies(requirements, case_studies, top_n=5):
    """Score and rank case studies against extracted requirements.

    Pure function — no API call.
    Weights: keyword overlap 50%, industry match 30%, capability match 20%.
    Returns up to top_n results sorted by score descending.
    Each result dict: id, title, industry_full, ai_type, has_video, score, explanation.
    """
    req_keywords = [k.lower() for k in requirements.get("keywords", [])]
    industry_signals = [s.lower() for s in requirements.get("industry_signals", [])]
    capabilities = [c.lower() for c in requirements.get("capabilities_needed", [])]

    scored = []
    for cs in case_studies:
        content = (cs.get("slide_content") or "").lower()
        title_lower = (cs.get("title") or "").lower()
        industry_lower = (cs.get("industry_full") or "").lower()
        ai_type_lower = (cs.get("ai_type") or "").lower()
        searchable = content + " " + title_lower

        # Keyword overlap (weight 0.5)
        matched_kw = [k for k in req_keywords if k in searchable] if req_keywords else []
        kw_score = len(matched_kw) / len(req_keywords) if req_keywords else 0.0

        # Industry match (weight 0.3)
        ind_match = any(sig in industry_lower for sig in industry_signals) if industry_signals else False
        ind_score = 1.0 if ind_match else 0.0

        # Capability / AI type match (weight 0.2)
        matched_caps = [c for c in capabilities if c in ai_type_lower or c in searchable] if capabilities else []
        cap_score = min(len(matched_caps) / len(capabilities), 1.0) if capabilities else 0.0

        total = round((kw_score * 0.5 + ind_score * 0.3 + cap_score * 0.2) * 100, 1)

        parts = []
        if ind_match:
            parts.append(f"Industry match ({cs.get('industry_full')})")
        if matched_kw:
            parts.append(f"matched keywords: {', '.join(matched_kw[:4])}")
        if matched_caps:
            parts.append(f"AI capability overlap: {', '.join(matched_caps[:2])}")
        if not parts:
            parts.append("Partial content relevance")

        explanation = "; ".join(parts)
        if explanation and explanation[0].islower():
            explanation = explanation[0].upper() + explanation[1:]
        explanation = (explanation + ".") if not explanation.endswith(".") else explanation

        scored.append({
            "id": cs["id"],
            "title": cs["title"],
            "industry_full": cs.get("industry_full"),
            "ai_type": cs.get("ai_type"),
            "has_video": cs.get("has_video", 0),
            "score": total,
            "explanation": explanation[:300],
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
