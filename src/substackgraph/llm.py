"""LLM integration for Episode 3 draft generation.

Uses OpenRouter (OpenAI-compatible API) with plain requests — no SDK needed.
Set OPENROUTER_API_KEY in .env or environment. Falls back to stub templates
when the key is not set, with a clear warning.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-4-5"  # via OpenRouter

_api_key: str | None = None
_stub_mode = False


def _get_api_key() -> str | None:
    """Return the OpenRouter API key, loading .env if needed."""
    global _api_key, _stub_mode
    if _api_key is not None:
        return _api_key
    if _stub_mode:
        return None

    # Check env first
    key = os.environ.get("OPENROUTER_API_KEY")

    # Fall back to .env file in project root
    if not key:
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break

    if not key:
        print(
            "WARNING: OPENROUTER_API_KEY not set. Using stub templates for collab briefs "
            "and outreach angles. Set OPENROUTER_API_KEY in .env or environment.",
            file=sys.stderr,
        )
        _stub_mode = True
        return None

    _api_key = key
    return _api_key


def _call(prompt: str, max_tokens: int = 600) -> str:
    """Make a single OpenRouter chat completion call. Returns the response text."""
    key = _get_api_key()
    if key is None:
        raise RuntimeError("No API key")

    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/substackgraph",
            "X-Title": "substackgraph",
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def is_stub_mode() -> bool:
    """Check if we're in stub mode (no API key)."""
    return _get_api_key() is None


def generate_collab_brief(
    pub_a_name: str,
    pub_b_name: str,
    pub_a_desc: str,
    pub_b_desc: str,
    cluster_a: str | None,
    cluster_b: str | None,
    shared_recommenders: list[str],
    overlap_score: float,
) -> dict:
    """Generate a collaboration brief. Returns dict with 'brief', 'method', and optionally 'model'."""
    if _get_api_key() is None:
        return _stub_collab_brief(pub_a_name, pub_b_name, cluster_a, cluster_b)

    shared_str = ", ".join(shared_recommenders[:8]) if shared_recommenders else "none identified"

    prompt = f"""You are a Substack growth advisor helping two independent writers explore a collaboration.

Write a collaboration brief for these two publications. Be warm, direct, and peer-to-peer — not corporate.

**Publication A:** {pub_a_name}
{f'Description/recent posts: {pub_a_desc}' if pub_a_desc else '(no description available)'}
{f'Niche cluster: {cluster_a}' if cluster_a else ''}

**Publication B:** {pub_b_name}
{f'Description/recent posts: {pub_b_desc}' if pub_b_desc else '(no description available)'}
{f'Niche cluster: {cluster_b}' if cluster_b else ''}

**Network data:**
- Shared recommenders: {shared_str}
- Audience overlap score: {overlap_score:.2f} (0-1 scale, higher = more overlap)

Produce EXACTLY this structure (no markdown headers, no bullets beyond what's specified):

WHY THESE TWO FIT: [2-3 sentences on why these publications complement each other, grounded in the data above]

GUEST POST ANGLE: "[Working title]" — [1 sentence describing the angle and why it works for both audiences]

CROSS-RECOMMENDATION FRAMING:
- What {pub_a_name} says to their audience about {pub_b_name}: [1 sentence]
- What {pub_b_name} says to their audience about {pub_a_name}: [1 sentence]

Keep the total under 200 words. Be specific — reference actual names, clusters, and shared connections."""

    brief_text = _call(prompt, max_tokens=400)
    return {"brief": brief_text, "method": "llm_claude", "model": MODEL}


def generate_outreach_angles(
    pub_a_name: str,
    pub_b_name: str,
    pub_a_desc: str,
    pub_b_desc: str,
    warm_path: list[str],
    voice_compat_score: float,
) -> dict:
    """Generate 3 outreach angles. Returns dict with 'angles', 'method', and optionally 'model'."""
    if _get_api_key() is None:
        return _stub_outreach_angles(pub_a_name, pub_b_name)

    warm_path_str = " → ".join(warm_path) if warm_path else "no warm path found"
    intro_person = warm_path[1] if warm_path and len(warm_path) > 2 else None

    prompt = f"""You are helping a Substack writer ({pub_a_name}) craft outreach messages to another writer ({pub_b_name}).

**About {pub_a_name}:**
{pub_a_desc if pub_a_desc else '(no description available)'}

**About {pub_b_name}:**
{pub_b_desc if pub_b_desc else '(no description available)'}

**Network data:**
- Warm path: {warm_path_str}
{f'- Potential intro person: {intro_person}' if intro_person else '- No intermediary identified'}
- Voice compatibility score: {voice_compat_score:.2f} (0-1 scale)

Generate exactly 3 outreach angles as a JSON array. Each angle must be grounded in the actual data above — no generic pitches. Substack writers hate salesy or templated messages.

The 3 angles MUST be:
1. **Shared Network** — reference the actual warm path and shared connections
2. **Content Complement** — what each writer covers that the other doesn't, and why that creates value
3. **Warm Intro** — who could make the introduction and why they'd be willing

Each angle needs:
- "angle": the angle name (one of "Shared Network", "Content Complement", "Warm Intro")
- "subject": a specific email subject line (under 60 chars, not clickbaity)
- "body": exactly 3 sentences. Sentence 1: establish the connection. Sentence 2: the specific idea. Sentence 3: low-pressure ask.

Tone: genuine, specific, brief. Write like one writer DMing another, not like a PR agency.

Return ONLY the JSON array, no other text."""

    raw = _call(prompt, max_tokens=600).strip()
    # Extract JSON from response (handle potential markdown wrapping)
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    try:
        angles = json.loads(raw)
    except json.JSONDecodeError:
        # If JSON parsing fails, return the raw text as a single angle
        angles = [
            {"angle": "Raw Response", "subject": "Collaboration idea", "body": raw}
        ]

    return {"angles": angles, "method": "llm_claude", "model": MODEL}


# ---------------------------------------------------------------------------
# Stub fallbacks (no API key)
# ---------------------------------------------------------------------------

def _stub_collab_brief(
    pub_a_name: str, pub_b_name: str,
    cluster_a: str | None, cluster_b: str | None,
) -> dict:
    brief = (
        f"Collaboration Brief: {pub_a_name} x {pub_b_name}\n\n"
        f"Both publications operate in the Substack recommendation network.\n"
        f"{pub_a_name} is in cluster: {cluster_a or 'unknown'}\n"
        f"{pub_b_name} is in cluster: {cluster_b or 'unknown'}\n\n"
        f"Potential angles:\n"
        f"1. Guest post swap exploring the intersection of both audiences\n"
        f"2. Joint AMA or Q&A thread on shared topics\n"
        f"3. Cross-recommendation with personalized intro to each audience\n"
    )
    return {"brief": brief, "method": "stub_template"}


def _stub_outreach_angles(pub_a_name: str, pub_b_name: str) -> dict:
    return {
        "angles": [
            {
                "angle": "Shared Network",
                "subject": f"We share recommenders — collab idea",
                "body": (
                    f"Hey {pub_b_name} — I noticed we share several recommenders in common. "
                    f"Our audiences likely overlap and I think there's a natural fit. "
                    f"Would you be open to exploring a cross-recommendation?"
                ),
            },
            {
                "angle": "Content Complement",
                "subject": f"Your readers might like {pub_a_name}",
                "body": (
                    f"Hi {pub_b_name} — I write {pub_a_name} and your work complements mine well. "
                    f"I think a guest post swap could introduce both our audiences to fresh perspectives. "
                    f"Happy to share more details if you're interested."
                ),
            },
            {
                "angle": "Warm Intro",
                "subject": f"Intro via a mutual connection",
                "body": (
                    f"Hi {pub_b_name} — a mutual recommender pointed me to your work. "
                    f"I'd love to explore a collaboration that serves both our audiences. "
                    f"No pressure — just thought I'd reach out."
                ),
            },
        ],
        "method": "stub_template",
    }
