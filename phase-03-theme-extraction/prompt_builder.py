"""
prompt_builder.py — Phase 03: Theme Extraction
------------------------------------------------
Builds a single, compact LLM prompt from the clean reviews.

Design goals:
  - ONE API call per pipeline run (enforced by theme_extractor.py).
  - Stratified sampling: proportional representation across weeks and
    ratings so the LLM sees a balanced picture, not just low-rated rage.
  - Token-safe: cap at MAX_REVIEWS_IN_PROMPT (default 120) so the prompt
    stays well inside the model's context window.

Output of build_prompt():
  A complete string ready to be sent as the user message to Groq.
  The system prompt is kept separate so callers can compose freely.
"""

import random
from collections import defaultdict
from typing import Any

# Maximum reviews to include in the prompt (keeps token budget safe)
MAX_REVIEWS_IN_PROMPT = 120

SYSTEM_PROMPT = """You are a senior product analyst. Your job is to read real app store reviews
and extract the dominant themes users talk about.

**Output rules — follow exactly:**
- Respond with ONLY valid JSON. No prose, no markdown fences.
- The JSON must have a single top-level key: "themes" (an array).
- Each theme object must have:
    "theme_name"   : short label (3-5 words)
    "description"  : one sentence explaining the theme
    "sentiment"    : "positive" | "negative" | "mixed"
    "review_count" : approximate number of reviews mentioning this theme
    "avg_rating"   : average rating of those reviews (1 decimal, float)
    "example_quotes": list of 2-3 verbatim short quotes from the reviews
- Return 6-10 themes, ordered by review_count descending.
- Do NOT include themes with fewer than 3 mentions.
"""


def build_prompt(reviews: list[dict[str, Any]], max_reviews: int = MAX_REVIEWS_IN_PROMPT) -> str:
    """
    Sample and format reviews into a single user prompt.

    Args:
        reviews:     List of clean review dicts (from reviews_clean.json).
        max_reviews: Maximum number of reviews to include in the prompt.

    Returns:
        A formatted string to be passed as the user message to the LLM.
    """
    sampled = _stratified_sample(reviews, max_reviews)

    lines = [
        f"Below are {len(sampled)} app store reviews for analysis.",
        "Extract the dominant themes as described in your instructions.",
        "",
        "--- REVIEWS ---",
    ]

    for i, r in enumerate(sampled, 1):
        rating  = r.get("rating", "?")
        platform = r.get("platform", "?").upper()
        body    = (r.get("body") or "").strip().replace("\n", " ")
        week    = r.get("week_id", "")
        # Truncate very long bodies to keep token count reasonable
        if len(body) > 300:
            body = body[:297] + "..."
        lines.append(f"[{i}] ({platform} | {rating}★ | {week}) {body}")

    lines.append("")
    lines.append("Respond with the JSON object now.")
    return "\n".join(lines)


def _stratified_sample(
    reviews: list[dict[str, Any]],
    n: int,
) -> list[dict[str, Any]]:
    """
    Sample reviews proportionally across (week × rating_bucket).
    rating_bucket: 'low' (1-2), 'mid' (3), 'high' (4-5).

    Falls back to random shuffle if fewer reviews than n.
    """
    if len(reviews) <= n:
        return list(reviews)

    # Group by (week_id, rating_bucket)
    buckets: defaultdict[tuple, list] = defaultdict(list)
    for r in reviews:
        week   = r.get("week_id", "unknown")
        rating = int(r.get("rating", 3))
        bucket = "low" if rating <= 2 else ("mid" if rating == 3 else "high")
        buckets[(week, bucket)].append(r)

    # Proportional allocation
    total = len(reviews)
    sampled: list[dict] = []
    for key, group in buckets.items():
        quota = max(1, round(n * len(group) / total))
        sampled.extend(random.sample(group, min(quota, len(group))))

    # Trim or top-up to exactly n
    random.shuffle(sampled)
    if len(sampled) > n:
        sampled = sampled[:n]
    elif len(sampled) < n:
        remaining = [r for r in reviews if r not in sampled]
        sampled.extend(random.sample(remaining, min(n - len(sampled), len(remaining))))

    return sampled
