"""
executive_insights.py — Phase 06: Executive Insights
---------------------------------------------------
A curation phase that takes raw output from Themes (P03), Pulse (P04), and 
Actions (P05) and reduces them to a strict "Top 3" JSON format.

This ensures that PDF and Email phases have identical, pre-approved data.
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
# LLM Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior product manager curating a weekly executive briefing.

**Your Goal:**
Select exactly 3 themes, 3 user quotes, and 3 action items from the provided data.

**Output rules:**
- Respond with ONLY valid JSON.
- JSON keys:
    "top_themes": list of objects [{name, sentiment, description}]
    "top_quotes": list of strings (punchy and representative)
    "top_actions": list of objects [{title, description, priority}]
- Length: Exactly 3 items per list.
- Accuracy: Use the provided data only.
- Selection: Prioritize high-impact negative/mixed themes and P1 actions.
"""

def _build_insights_prompt(themes: list[dict], pulse: dict, actions: list[dict]) -> str:
    context_lines = [
        "RAW THEMES DATA:",
    ]
    for t in themes[:8]:
        context_lines.append(f"- [{t['sentiment'].upper()}] {t['theme_name']}: {t['description']}")
        if t.get('example_quotes'):
            context_lines.append(f"  Quotes: {t['example_quotes'][:2]}")
    
    context_lines += [
        "",
        "ACTION ITEMS DATA:",
    ]
    for a in actions[:6]:
        context_lines.append(f"- [{a['priority']}] {a['title']}: {a['description']}")
    
    context_lines += [
        "",
        f"HEALTH SCORE: {pulse.get('health_score')}/100",
        f"PULSE SUMMARY: {pulse.get('summary')}",
        "",
        "Select the top 3 themes, 3 quotes, and 3 actions for the executive report now."
    ]
    return "\n".join(context_lines)


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    logger.info("Phase 06 — Executive Insights: starting.")
    start = time.monotonic()

    data_root    = Path(config.get("data_root", "data"))
    themes_path  = data_root / week_id / "03-themes" / "themes.json"
    pulse_path   = data_root / week_id / "04-pulse" / "pulse.json"
    actions_path = data_root / week_id / "05-actions" / "actions.json"
    output_dir   = data_root / week_id / "06-insights"
    output_dir.mkdir(parents=True, exist_ok=True)
    insights_path = output_dir / "insights.json"

    # Idempotency
    if insights_path.exists():
        logger.info(f"  insights.json exists — skipping. ({insights_path})")
        return

    # Load inputs
    for p in [themes_path, pulse_path, actions_path]:
        if not p.exists():
            raise RuntimeError(f"Phase 06: Input missing -> {p}")

    with open(themes_path) as f: themes = json.load(f).get("themes", [])
    with open(pulse_path) as f: pulse = json.load(f)
    with open(actions_path) as f: actions = json.load(f).get("actions", [])

    # Single call to LLM to curate
    llm_cfg     = config.get("llm", {})
    model       = llm_cfg.get("model_name", "llama-3.3-70b-versatile")
    api_key_var = llm_cfg.get("api_key_env_var", "GROQ_API_KEY")
    api_key     = os.environ.get(api_key_var)

    if not api_key:
        raise RuntimeError(f"Phase 06: Missing '{api_key_var}' environment variable.")

    logger.info(f"  Curating Top 3 data using {model}...")
    raw_response = _call_groq(
        api_key=api_key, model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_build_insights_prompt(themes, pulse, actions)
    )
    
    insights_data = _parse_response(raw_response)
    
    # Save output
    output = {
        "week_id": week_id,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model": model,
        "insights": insights_data
    }
    
    with open(insights_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    elapsed = time.monotonic() - start
    logger.info(f"Phase 06 — Executive Insights: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_groq(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content

def _parse_response(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise RuntimeError("Phase 06: Failed to parse LLM JSON response.")

if __name__ == "__main__":
    # Test stub
    import yaml
    from dotenv import load_dotenv
    load_dotenv()
    with open(_PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml") as f:
        cfg = yaml.safe_load(f)
    
    _logging = logging.getLogger("test")
    _logging.setLevel(logging.INFO)
    _logging.addHandler(logging.StreamHandler())
    
    run(week_id="historical-12w", config=cfg, logger=_logging)
