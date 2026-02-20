"""
action_generator.py — Phase 05: Action Items
---------------------------------------------
Generates a prioritised list of PM-ready action items from the pulse
and themes produced by Phases 03 & 04.

Design:
  - Input : data/{run_label}/04-pulse/pulse.json
             data/{run_label}/03-themes/themes.json
  - Output: data/{run_label}/05-actions/actions.json
  - ONE Groq API call per run (idempotency guard: skip if actions.json exists).
  - No API call if the output already exists.

Action item schema (per item):
  {
    "priority":     "P1" | "P2" | "P3",
    "category":     "Bug Fix" | "Feature" | "UX" | "Support" | "Trust & Safety" | "Other",
    "title":        short action title (≤10 words),
    "description":  1-2 sentence explanation of what to do and why,
    "theme_source": theme_name this action is derived from,
    "effort":       "Low" | "Medium" | "High",
    "expected_impact": one sentence on the user-facing benefit
  }
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


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior product manager creating a prioritised action plan from app review insights.

**Output rules — follow exactly:**
- Respond with ONLY valid JSON. No prose, no markdown.
- Top-level key: "actions" (an array of action objects).
- Each action object must have ALL of these keys:
    "priority"         : "P1" (critical, fix this week) | "P2" (important, this sprint) | "P3" (nice-to-have)
    "category"         : "Bug Fix" | "Feature" | "UX" | "Support" | "Trust & Safety" | "Other"
    "title"            : action title, max 10 words
    "description"      : 1-2 sentences explaining what to do and why
    "theme_source"     : which theme this comes from
    "effort"           : "Low" | "Medium" | "High"
    "expected_impact"  : one sentence on the user-facing benefit
- Return exactly 3 actions, ordered P1 -> P2 -> P3.
- Every P1 must come from a negative or mixed theme.
- Be specific and actionable. Avoid vague recommendations.
"""


def _build_action_prompt(pulse: dict, themes: list[dict], week_id: str) -> str:
    lines = [
        f"App Review Action Plan — {week_id}",
        f"Health Score: {pulse.get('health_score', '?')}/100 ({pulse.get('health_label', '?')})",
        f"Avg Rating  : {pulse.get('weighted_avg_rating', '?')}/5.0",
        "",
        f"Summary    : {pulse.get('summary', '')}",
        f"PM Note    : {pulse.get('pm_note', '')}",
        f"Top Neg    : {', '.join(pulse.get('top_negatives', []))}",
        f"Watch List : {', '.join(pulse.get('watch_list', []))}",
        "",
        "Themes (ordered by volume):",
    ]
    for t in themes:
        lines.append(
            f"  [{t.get('sentiment','?').upper()}] {t.get('theme_name','')} "
            f"| {t.get('review_count',0)} reviews | {t.get('avg_rating',0)}★ "
            f"| {t.get('description','')} "
            f"| Quotes: {t.get('example_quotes',[])}"
        )
    lines += ["", "Generate the actions JSON now."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute Action Item generation.

    Guarantees:
      - At most ONE Groq API call per invocation.
      - Zero API calls if actions.json already exists.
    """
    logger.info("Phase 05 — Action Items: starting.")
    start = time.monotonic()

    data_root    = Path(config.get("data_root", "data"))
    pulse_path   = data_root / week_id / "04-pulse"  / "pulse.json"
    themes_path  = data_root / week_id / "03-themes" / "themes.json"
    output_dir   = data_root / week_id / "05-actions"
    output_dir.mkdir(parents=True, exist_ok=True)
    actions_path = output_dir / "actions.json"

    # ── Idempotency guard ────────────────────────────────────────────────────
    if actions_path.exists():
        logger.info(f"  actions.json already exists — skipping API call. ({actions_path})")
        return

    # ── Load inputs ──────────────────────────────────────────────────────────
    for path, label in [(pulse_path, "pulse.json"), (themes_path, "themes.json")]:
        if not path.exists():
            raise RuntimeError(f"Phase 05: input not found: {path} ({label})")

    with open(pulse_path,  encoding="utf-8") as f:
        pulse: dict = json.load(f)
    with open(themes_path, encoding="utf-8") as f:
        themes_doc: dict = json.load(f)

    themes = themes_doc.get("themes", [])
    logger.info(f"  Loaded pulse (score={pulse.get('health_score')}) and {len(themes)} themes.")

    # ── Build prompt ─────────────────────────────────────────────────────────
    user_prompt = _build_action_prompt(pulse, themes, week_id)

    # ── Single Groq API call ─────────────────────────────────────────────────
    llm_cfg     = config.get("llm", {})
    model       = llm_cfg.get("model_name", "llama-3.3-70b-versatile")
    api_key_var = llm_cfg.get("api_key_env_var", "GROQ_API_KEY")
    api_key     = os.environ.get(api_key_var)

    if not api_key:
        raise RuntimeError(
            f"Phase 05: environment variable '{api_key_var}' is not set."
        )

    logger.info(f"  Calling Groq API (model={model}) — ONE call only ...")
    raw_response = _call_groq(
        api_key=api_key, model=model,
        system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt
    )
    logger.info("  API call complete.")

    # ── Parse & write ────────────────────────────────────────────────────────
    parsed   = _parse_response(raw_response)
    actions  = parsed.get("actions", [])

    output = {
        "week_id":      week_id,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model":        model,
        "health_score": pulse.get("health_score"),
        "health_label": pulse.get("health_label"),
        "action_count": len(actions),
        "actions":      actions,
    }

    with open(actions_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"  Actions written → {actions_path} ({len(actions)} items)")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 05 — Action Items: complete in {elapsed:.1f}s.")


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
        temperature=0.2,
        max_tokens=2048,
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
        f"Phase 05: could not parse LLM response as JSON.\n"
        f"Raw (first 400 chars): {raw[:400]}"
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run Phase 05 — Action Items standalone.")
    parser.add_argument("--run-label", required=True, help="e.g. historical-12w")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing actions.json and re-generate (costs 1 API call)")
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
        cached = Path(cfg["data_root"]) / args.run_label / "05-actions" / "actions.json"
        if cached.exists():
            cached.unlink()
            print(f"[--force] Deleted cached {cached}")

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase05.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
