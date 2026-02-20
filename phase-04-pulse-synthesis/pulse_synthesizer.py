"""
pulse_synthesizer.py — Phase 04: Pulse Synthesis
--------------------------------------------------
Entry point for the Pulse Synthesis phase.

Responsibilities:
  1. Load themes.json from Phase 03.
  2. Compute quantitative health score (score_calculator — no LLM).
  3. Make EXACTLY ONE Groq API call per run to generate the narrative pulse.
  4. Write pulse.json with score + narrative to data/{run_label}/04-pulse/.

API call guarantee:
  - Idempotency: if pulse.json already exists, skip entirely (zero calls).
  - Single batch: theme list + pre-computed score → one prompt → one response.
  - --force flag available for standalone runs to delete and re-generate.
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Path bootstrap
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from phase_04_pulse_synthesis.score_calculator import compute_health_score
except ImportError:
    from score_calculator import compute_health_score


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior product manager writing a weekly Product Health Pulse report.
Your audience is the internal PM and leadership team.

**Output rules — follow exactly:**
- Respond with ONLY valid JSON. No prose, no markdown fences.
- The JSON must have exactly these keys:
    "summary"       : 2-3 sentence plain-English narrative of the week's app health
    "top_positives" : list of 2-3 theme_name strings (best performing themes)
    "top_negatives" : list of 2-3 theme_name strings (most critical pain points)
    "watch_list"    : list of 0-3 theme_name strings needing PM attention
    "pm_note"       : one actionable sentence the PM team should act on this week
- Be concise, factual, and avoid vague language. Use the data provided.
"""


def _build_pulse_prompt(themes: list[dict], score_data: dict, week_id: str) -> str:
    """Build the single user prompt for pulse synthesis."""
    lines = [
        f"Weekly App Review Pulse — {week_id}",
        f"Health Score: {score_data['health_score']}/100 ({score_data['health_label']})",
        f"Weighted Avg Rating: {score_data['weighted_avg_rating']}/5.0",
        f"Total Reviews Analysed: {score_data['total_reviews']}",
        "",
        "Extracted Themes (ordered by volume):",
    ]
    for t in themes:
        lines.append(
            f"  - [{t.get('sentiment','?').upper()}] {t.get('theme_name','')} "
            f"| {t.get('review_count',0)} reviews | {t.get('avg_rating',0)}★ "
            f"| \"{t.get('description','')}\" "
            f"| Quotes: {t.get('example_quotes', [])}"
        )
    lines += ["", "Generate the pulse JSON now."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute Pulse Synthesis.

    Guarantees:
      - At most ONE Groq API call per invocation.
      - Zero API calls if pulse.json already exists.
    """
    logger.info("Phase 04 — Pulse Synthesis: starting.")
    start = time.monotonic()

    data_root   = Path(config.get("data_root", "data"))
    input_path  = data_root / week_id / "03-themes" / "themes.json"
    output_dir  = data_root / week_id / "04-pulse"
    output_dir.mkdir(parents=True, exist_ok=True)
    pulse_path  = output_dir / "pulse.json"

    # ── Idempotency guard ───────────────────────────────────────────────────
    if pulse_path.exists():
        logger.info(f"  pulse.json already exists — skipping API call. ({pulse_path})")
        return

    # ── Load themes ─────────────────────────────────────────────────────────
    if not input_path.exists():
        raise RuntimeError(f"Phase 04: input not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        themes_doc: dict = json.load(f)

    themes = themes_doc.get("themes", [])
    logger.info(f"  Loaded {len(themes)} themes from Phase 03.")

    # ── Compute score (no LLM) ──────────────────────────────────────────────
    score_data = compute_health_score(themes)
    logger.info(
        f"  Health score: {score_data['health_score']}/100 "
        f"({score_data['health_label']}) — computed without API call."
    )

    # ── Build prompt ────────────────────────────────────────────────────────
    user_prompt = _build_pulse_prompt(themes, score_data, week_id)

    # ── Single Groq API call ─────────────────────────────────────────────────
    llm_cfg     = config.get("llm", {})
    model       = llm_cfg.get("model_name", "llama-3.3-70b-versatile")
    api_key_var = llm_cfg.get("api_key_env_var", "GROQ_API_KEY")
    api_key     = os.environ.get(api_key_var)

    if not api_key:
        raise RuntimeError(
            f"Phase 04: environment variable '{api_key_var}' is not set."
        )

    logger.info(f"  Calling Groq API (model={model}) — ONE call only ...")
    raw_response = _call_groq(
        api_key=api_key, model=model,
        system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt
    )
    logger.info("  API call complete.")

    # ── Parse & merge ────────────────────────────────────────────────────────
    narrative = _parse_response(raw_response)

    output = {
        "week_id":              week_id,
        "generated_at":         datetime.now(tz=timezone.utc).isoformat(),
        "model":                model,
        # Quantitative (computed, deterministic)
        "health_score":         score_data["health_score"],
        "health_label":         score_data["health_label"],
        "weighted_avg_rating":  score_data["weighted_avg_rating"],
        "total_reviews":        score_data["total_reviews"],
        # Narrative (LLM-generated)
        "summary":              narrative.get("summary", ""),
        "top_positives":        narrative.get("top_positives", []),
        "top_negatives":        narrative.get("top_negatives", []),
        "watch_list":           narrative.get("watch_list", []),
        "pm_note":              narrative.get("pm_note", ""),
    }

    with open(pulse_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"  Pulse written → {pulse_path}")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 04 — Pulse Synthesis: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_groq(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    """Single Groq call — isolated for easy mocking in tests."""
    from groq import Groq
    client   = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _parse_response(raw: str) -> dict:
    """Parse LLM JSON response with regex fallback."""
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise RuntimeError(
        f"Phase 04: could not parse LLM response as JSON.\n"
        f"Raw (first 400 chars): {raw[:400]}"
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run Phase 04 — Pulse Synthesis standalone.")
    parser.add_argument("--run-label", required=True, help="e.g. historical-12w")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing pulse.json and re-generate (costs 1 API call)")
    args = parser.parse_args()

    import yaml
    config_yaml = _PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    cfg = {
        "data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data")),
        "llm":       yaml_cfg.get("llm", {}),
    }

    if args.force:
        cached = Path(cfg["data_root"]) / args.run_label / "04-pulse" / "pulse.json"
        if cached.exists():
            cached.unlink()
            print(f"[--force] Deleted cached {cached}")

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase04.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
