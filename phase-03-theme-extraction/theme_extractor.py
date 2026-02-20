"""
theme_extractor.py — Phase 03: Theme Extraction
-------------------------------------------------
Entry point for the theme extraction phase. Makes EXACTLY ONE Groq API call
per pipeline run and skips entirely if the output already exists.

Key design decisions:
  1. Idempotency guard: if themes.json already exists for this run_label,
     the function returns immediately without any API call.
  2. Single-batch call: all sampled reviews are sent in ONE prompt. No loops,
     no per-review calls.
  3. Graceful JSON parsing: if the model adds prose around the JSON, we
     extract the first {...} block rather than failing.
  4. The Groq client is constructed lazily so tests can patch it easily.
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

# Path bootstrap for standalone execution
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from phase_03_theme_extraction.prompt_builder import build_prompt, SYSTEM_PROMPT
except ImportError:
    from prompt_builder import build_prompt, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Phase entry point (called by Phase 00 dispatcher)
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute Theme Extraction for a given run.

    Guarantees:
      - At most ONE Groq API call per invocation.
      - Zero API calls if output already exists (idempotency).

    Args:
        week_id: Run label (e.g. 'historical-12w' or '2026-W08').
        config:  Pipeline config dict.
        logger:  Bound logger.

    Raises:
        RuntimeError: On API or parsing failure.
    """
    logger.info("Phase 03 — Theme Extraction: starting.")
    start = time.monotonic()

    data_root  = Path(config.get("data_root", "data"))
    input_path = data_root / week_id / "02-clean" / "reviews_clean.json"
    output_dir = data_root / week_id / "03-themes"
    output_dir.mkdir(parents=True, exist_ok=True)
    themes_path = output_dir / "themes.json"

    # ── Idempotency guard ────────────────────────────────────────────────────
    if themes_path.exists():
        logger.info(f"  themes.json already exists — skipping API call. ({themes_path})")
        return

    # ── Load clean reviews ───────────────────────────────────────────────────
    if not input_path.exists():
        raise RuntimeError(f"Phase 03: input not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        reviews: list[dict] = json.load(f)

    logger.info(f"  Loaded {len(reviews)} clean reviews.")

    # ── Build prompt ─────────────────────────────────────────────────────────
    user_prompt = build_prompt(reviews)
    logger.info(f"  Prompt built ({len(user_prompt)} chars, covers up to 120 sampled reviews).")

    # ── Single Groq API call ─────────────────────────────────────────────────
    llm_cfg     = config.get("llm", {})
    model       = llm_cfg.get("model_name", "llama3-8b-8192")
    api_key_var = llm_cfg.get("api_key_env_var", "GROQ_API_KEY")
    api_key     = os.environ.get(api_key_var)

    if not api_key:
        raise RuntimeError(
            f"Phase 03: environment variable '{api_key_var}' is not set. "
            "Add it to your .env file."
        )

    logger.info(f"  Calling Groq API (model={model}) — ONE call only ...")
    raw_response = _call_groq(api_key=api_key, model=model,
                              system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    logger.info("  API call complete.")

    # ── Parse response ───────────────────────────────────────────────────────
    themes_data = _parse_response(raw_response)

    # ── Write output ─────────────────────────────────────────────────────────
    output = {
        "week_id":       week_id,
        "extracted_at":  datetime.now(tz=timezone.utc).isoformat(),
        "model":         model,
        "reviews_in_prompt": min(len(reviews), 120),
        "total_reviews": len(reviews),
        "themes":        themes_data.get("themes", []),
    }

    with open(themes_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"  Themes written → {themes_path} ({len(output['themes'])} themes)")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 03 — Theme Extraction: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_groq(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    """
    Make a single Groq chat completion call.

    Separated into its own function so unit tests can patch it easily:
        with patch('phase_03_theme_extraction.theme_extractor._call_groq', return_value=...):

    Returns:
        The raw content string from the assistant's message.
    """
    from groq import Groq  # lazy import — keeps startup fast when Groq not needed

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,    # low temp → more deterministic theme naming
        max_tokens=2048,
        response_format={"type": "json_object"},  # forces JSON output
    )
    return response.choices[0].message.content


def _parse_response(raw: str) -> dict:
    """
    Parse the LLM response into a dict.

    Tries strict json.loads first; if that fails, extracts the first
    {...} block from the text (handles stray prose around the JSON).

    Raises:
        RuntimeError: If no valid JSON can be extracted.
    """
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: grab the first {...} block
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Phase 03: could not parse LLM response as JSON.\n"
        f"Raw response (first 500 chars):\n{raw[:500]}"
    )


# ---------------------------------------------------------------------------
# Direct execution for local testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()  # pick up GROQ_API_KEY from .env

    parser = argparse.ArgumentParser(description="Run Phase 03 — Theme Extraction standalone.")
    parser.add_argument("--run-label", required=True,
                        help="Run label, e.g. historical-12w or 2026-W08")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing themes.json and re-run (costs 1 API call)")
    args = parser.parse_args()

    import yaml
    config_yaml = _PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    cfg = {
        "data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data")),
        "llm":       yaml_cfg.get("llm", {}),
    }

    # --force: remove cached output so we actually call the API
    if args.force:
        cached = Path(cfg["data_root"]) / args.run_label / "03-themes" / "themes.json"
        if cached.exists():
            cached.unlink()
            print(f"[--force] Deleted cached {cached}")

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase03.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
