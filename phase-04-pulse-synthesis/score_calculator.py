"""
score_calculator.py — Phase 04: Pulse Synthesis
-------------------------------------------------
Computes a quantitative Product Health Score from extracted themes.
Pure math — no LLM, no I/O. Easily unit-testable.

Score formula:
  weighted_avg_rating = sum(theme.avg_rating * theme.review_count)
                        / sum(theme.review_count)
  health_score (0-100) = (weighted_avg_rating / 5) * 100

  sentiment_penalty: each dominant negative theme (>10% of reviews,
  sentiment=negative) subtracts up to 5 points.

Labels:
  80–100 → Healthy
  60–79  → Stable
  40–59  → At Risk
  0–39   → Critical
"""

from typing import Any


LABEL_THRESHOLDS = [
    (80, "Healthy"),
    (60, "Stable"),
    (40, "At Risk"),
    (0,  "Critical"),
]


def compute_health_score(themes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute health score and label from a list of theme dicts.

    Args:
        themes: List of theme objects from themes.json.

    Returns:
        dict with keys: health_score (int 0-100), health_label (str),
        weighted_avg_rating (float), total_reviews (int).
    """
    if not themes:
        return {
            "health_score": 0,
            "health_label": "Critical",
            "weighted_avg_rating": 0.0,
            "total_reviews": 0,
        }

    total_reviews = sum(t.get("review_count", 0) for t in themes)
    if total_reviews == 0:
        return {
            "health_score": 0,
            "health_label": "Critical",
            "weighted_avg_rating": 0.0,
            "total_reviews": 0,
        }

    # Weighted average rating across all themes
    weighted_sum = sum(
        t.get("avg_rating", 3.0) * t.get("review_count", 0)
        for t in themes
    )
    weighted_avg = weighted_sum / total_reviews

    # Base score
    score = (weighted_avg / 5.0) * 100

    # Sentiment penalty: prominent negative themes pull score down
    for t in themes:
        if t.get("sentiment") == "negative":
            share = t.get("review_count", 0) / total_reviews
            if share > 0.10:          # >10% of reviews in a negative theme
                score -= min(5, share * 20)   # max 5pt penalty each

    score = max(0, min(100, round(score)))

    label = _score_to_label(score)

    return {
        "health_score":       score,
        "health_label":       label,
        "weighted_avg_rating": round(weighted_avg, 2),
        "total_reviews":      total_reviews,
    }


def _score_to_label(score: int) -> str:
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "Critical"
