import array
import os
import json
import re
import logging

import anthropic
import openai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── API clients ───────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — add it to .env to enable embedding generation"
            )
        _openai_client = openai.OpenAI(api_key=api_key)
    return _openai_client


# ── Anthropic helpers ─────────────────────────────────────────────────────────

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


# ── Embedding helpers ─────────────────────────────────────────────────────────

def _cosine_similarity(a, b):
    """Cosine similarity between two equal-length float sequences."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _serialize_embedding(embedding):
    """Pack a list of floats into a bytes BLOB (float32, little-endian)."""
    return array.array("f", embedding).tobytes()


def _deserialize_embedding(blob):
    """Unpack a bytes BLOB back into a list of floats."""
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def _build_rfp_embedding_text(brief):
    """Build compact text for RFP embedding from a structured brief dict.

    Uses objective + challenges + capabilities_needed — strips procurement boilerplate.
    """
    parts = []
    objective = (brief.get("objective") or "").strip()
    if objective:
        parts.append(objective)
    challenges = brief.get("challenges") or []
    if challenges:
        parts.append("Challenges: " + "; ".join(challenges))
    caps = brief.get("capabilities_needed") or []
    if caps:
        parts.append("Capabilities: " + ", ".join(caps))
    return "\n".join(parts)


def _build_cs_embedding_text(slide_content):
    """Build text for case study embedding using extracted Challenge/Approach/Results sections.

    Falls back to raw slide content when no structured sections are found.
    """
    sections = _extract_sections(slide_content or "")
    if sections:
        parts = []
        for key in ("challenge", "approach", "results"):
            if key in sections:
                parts.append(f"{key.capitalize()}: {sections[key]}")
        return "\n".join(parts)
    return (slide_content or "").strip()


def generate_embedding(text):
    """Generate an embedding vector using OpenAI text-embedding-3-small.

    Returns a list of floats.
    Raises RuntimeError on API failure or missing API key.
    """
    try:
        response = _get_openai_client().embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
    except openai.APIStatusError as e:
        raise RuntimeError(f"OpenAI API error ({e.status_code}): {e.message}") from e
    except openai.APIConnectionError as e:
        raise RuntimeError(f"Could not connect to OpenAI API: {e}") from e


def store_embeddings():
    """Generate and store embeddings for any case study that does not have one yet.

    Returns {"generated": int, "failed": int}.
    Never raises — failures are logged and counted.
    """
    from db import get_case_studies_without_embeddings, store_case_study_embedding

    candidates = get_case_studies_without_embeddings()
    if not candidates:
        logger.info("store_embeddings: all case studies already have embeddings")
        return {"generated": 0, "failed": 0}

    generated = failed = 0
    for cs in candidates:
        try:
            text = _build_cs_embedding_text(cs.get("slide_content") or "")
            if not text.strip():
                logger.warning("Case study %d %r has no content to embed — skipping", cs["id"], cs.get("title"))
                failed += 1
                continue
            embedding = generate_embedding(text)
            blob = _serialize_embedding(embedding)
            store_case_study_embedding(cs["id"], blob, "text-embedding-3-small")
            generated += 1
        except Exception as e:
            logger.error("Failed to embed case study %d %r: %s", cs["id"], cs.get("title"), e)
            failed += 1

    logger.info("store_embeddings: %d generated, %d failed", generated, failed)
    return {"generated": generated, "failed": failed}


# ── Matching ──────────────────────────────────────────────────────────────────

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


def match_case_studies(rfp_text, case_studies, brief_capabilities=None, brief=None):
    """Match RFP text against case studies using embedding pre-selection + Claude reasoning.

    Step 1 (free, instant): cosine similarity between RFP embedding and stored case study
    embeddings — returns top 10 candidates.
    Step 2 (Claude API): deep reasoning on those candidates — score, explanation, matched_caps.

    Falls back to sending all case studies to Claude when no embeddings are stored.
    Returns up to 5 dicts above score 25: {id, title, industry_full, engagement_type,
    has_video, score, explanation, matched_caps}.
    Raises RuntimeError on API failure, ValueError if response is not valid JSON.
    """
    if not case_studies:
        return []

    capabilities = brief_capabilities or []

    # ── Step 1: embedding-based pre-selection ─────────────────────────────────
    cs_with_emb = [cs for cs in case_studies if cs.get("embedding")]
    if cs_with_emb:
        if brief is None:
            brief = generate_brief(rfp_text)
        rfp_emb_text = _build_rfp_embedding_text(brief)
        rfp_emb = generate_embedding(rfp_emb_text)

        sims = []
        for cs in cs_with_emb:
            cs_emb = _deserialize_embedding(cs["embedding"])
            sims.append((_cosine_similarity(rfp_emb, cs_emb), cs))
        sims.sort(key=lambda x: x[0], reverse=True)
        candidates = [cs for _, cs in sims[:10]]
        logger.info(
            "Embedding pre-selection: %d candidates from %d case studies (%d had embeddings)",
            len(candidates), len(case_studies), len(cs_with_emb),
        )
    else:
        logger.warning(
            "No stored embeddings — sending all %d case studies to Claude", len(case_studies)
        )
        candidates = case_studies

    # ── Step 2: Claude deep reasoning ─────────────────────────────────────────
    cs_payload = []
    for cs in candidates:
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
