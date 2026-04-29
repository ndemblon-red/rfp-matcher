# AI / LLM Integration Patterns Reference

This file contains all patterns for integrating the Anthropic Claude API into ADL Catalyst applications. Read this file when creating or modifying `analysis.py` or any AI-related code.

## Table of Contents

1. [Core Helper Functions](#core-helper-functions)
2. [AI Function Pattern](#ai-function-pattern)
3. [JSON Response Handling](#json-response-handling)
4. [SSE Streaming Pattern](#sse-streaming-pattern)
5. [Error Handling & Resilience](#error-handling--resilience)

---

## Core Helper Functions

Every application that uses AI features needs these two functions in `analysis.py`. They handle the API call and the JSON parsing respectively.

### `_call_claude`

```python
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def _call_claude(system, user, max_tokens=16384, temperature=0.2):
    """Call Claude API and return the response. Raises on API errors."""
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
```

### `_safe_parse_json`

AI responses sometimes include markdown fences or get truncated at `max_tokens`. This function handles both cases:

```python
import json
import re
import logging

logger = logging.getLogger(__name__)

def _safe_parse_json(text, context="unknown"):
    """Parse JSON from an AI response, handling fences and truncation."""
    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Attempt direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt truncation repair: close open braces/brackets
    repaired = cleaned
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")

    # Trim trailing incomplete key-value pair (after last comma)
    if open_braces > 0 or open_brackets > 0:
        last_comma = repaired.rfind(",")
        if last_comma > 0:
            repaired = repaired[:last_comma]

    repaired += "]" * open_brackets + "}" * open_braces

    try:
        result = json.loads(repaired)
        logger.warning(f"[{context}] Repaired truncated JSON ({open_braces} braces, {open_brackets} brackets)")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"[{context}] Failed to parse JSON even after repair: {e}")
        logger.error(f"[{context}] First 500 chars: {cleaned[:500]}")
        raise ValueError(f"AI response was not valid JSON in {context}") from e
```

---

## AI Function Pattern

Every AI feature function follows this template. The system prompt defines the expected JSON schema, and the function parses and returns structured data:

```python
def ai_analyse_thing(thing_data, agent_name="AI"):
    """Analyse a thing and return structured findings."""
    system = f"""You are {agent_name}, an expert analyst.
    
Analyse the provided data and respond with ONLY a JSON object:
{{
    "summary": "Brief overall summary",
    "findings": [
        {{
            "title": "Finding title",
            "detail": "Detailed explanation",
            "severity": "high|medium|low"
        }}
    ],
    "score": 0-100
}}

Respond with ONLY valid JSON. No markdown, no explanation."""

    user = f"Please analyse this data:\n\n{json.dumps(thing_data, indent=2)}"

    result = _call_claude(system=system, user=user, max_tokens=16384)

    if result["truncated"]:
        logger.warning("AI response was truncated — consider increasing max_tokens or reducing input")

    return _safe_parse_json(result["text"], "analyse_thing")
```

Key rules:
- Always specify the JSON schema in the system prompt.
- Always end the system prompt with "Respond with ONLY valid JSON."
- Always pass a descriptive `context` string to `_safe_parse_json` for debugging.
- Check `result["truncated"]` and log a warning — truncated JSON is the #1 cause of parse failures.
- Use `temperature=0.2` (the default) for analytical tasks. Use `0.5–0.7` for creative generation.

---

## SSE Streaming Pattern

For long-running AI tasks, use Server-Sent Events to show progress to the user:

```python
# In app.py — the SSE endpoint
from flask import Response, stream_with_context
import time

@app.route("/api/analyse/<int:thing_id>/stream")
def stream_analysis(thing_id):
    def generate():
        try:
            yield f"data: {json.dumps({'status': 'starting', 'message': 'Loading data...'})}\n\n"

            thing = get_thing(thing_id)
            yield f"data: {json.dumps({'status': 'processing', 'message': 'Analysing...'})}\n\n"

            result = ai_analyse_thing(thing)
            yield f"data: {json.dumps({'status': 'complete', 'result': result})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

For tasks taking more than ~15 seconds, add keepalive comments to prevent proxy timeouts:

```python
# In a long-running stream, send keepalives between steps:
yield ": keepalive\n\n"
```

### Client-Side SSE Consumption

```javascript
function runAnalysis(thingId, onUpdate, onComplete, onError) {
    const source = new EventSource(`/api/analyse/${thingId}/stream`);
    source.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.status === 'complete') {
            onComplete(data.result);
            source.close();
        } else if (data.status === 'error') {
            onError(data.message);
            source.close();
        } else {
            onUpdate(data.message);
        }
    };
    source.onerror = function() {
        onError('Connection lost');
        source.close();
    };
}
```

---

## Error Handling & Resilience

### Retry on Transient Failures

For production use, wrap AI calls with a simple retry for transient errors (rate limits, server errors):

```python
import time

def _call_claude_with_retry(system, user, max_tokens=16384, max_retries=2):
    """Call Claude with retry on transient failures."""
    for attempt in range(max_retries + 1):
        try:
            return _call_claude(system, user, max_tokens)
        except RuntimeError as e:
            error_msg = str(e)
            is_retryable = any(code in error_msg for code in ["429", "500", "502", "503"])
            if is_retryable and attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning(f"Retryable error, waiting {wait}s (attempt {attempt + 1}): {e}")
                time.sleep(wait)
            else:
                raise
```

### Graceful Degradation

When building pages that mix AI-generated and non-AI content, always degrade gracefully:

```python
try:
    ai_result = ai_analyse_thing(thing_data)
except Exception as e:
    logger.error(f"AI analysis failed: {e}")
    ai_result = None  # Template should show "Analysis unavailable" rather than crashing
```

In templates, check for `None` before rendering AI results:

```html
{% if analysis %}
    <div class="card">{{ analysis.summary }}</div>
{% else %}
    <div class="card" style="color: var(--text-dim);">
        Analysis is temporarily unavailable. Other features remain functional.
    </div>
{% endif %}
```
