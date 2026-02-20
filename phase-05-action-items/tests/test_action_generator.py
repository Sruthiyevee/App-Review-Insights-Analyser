"""
test_action_generator.py — Unit tests for Phase 05: Action Items
------------------------------------------------------------------
All tests are fully offline — Groq is mocked. No API keys required.

Test coverage:
  1.  Idempotency — skips API if actions.json exists
  2.  Happy path — exactly one _call_groq call, actions.json written with all keys
  3.  Actions list is non-empty in happy path
  4.  Priority ordering validated (P1 items present when negatives exist)
  5.  Missing pulse.json input → RuntimeError
  6.  Missing themes.json input → RuntimeError
  7.  Missing API key → RuntimeError
  8.  Bad LLM JSON → RuntimeError
  9.  _parse_response — valid JSON string
  10. _parse_response — JSON embedded in prose
  11. _parse_response — invalid → RuntimeError
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Path bootstrap ───────────────────────────────────────────────────────────
_TESTS_DIR    = Path(__file__).resolve().parent
_PHASE_DIR    = _TESTS_DIR.parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from action_generator import run, _parse_response  # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────

NULL_LOGGER = logging.getLogger("test.null")
NULL_LOGGER.addHandler(logging.NullHandler())

SAMPLE_PULSE = {
    "week_id":             "test-week",
    "health_score":        74,
    "health_label":        "Stable",
    "weighted_avg_rating": 3.7,
    "total_reviews":       133,
    "summary":             "App is stable with some support pain points.",
    "top_positives":       ["Good Experience", "Investment Features"],
    "top_negatives":       ["Customer Support Issues", "Technical Issues"],
    "watch_list":          ["App Interface"],
    "pm_note":             "Prioritise customer support resolution.",
}

SAMPLE_THEMES_DOC = {
    "week_id": "test-week",
    "themes": [
        {
            "theme_name":     "Customer Support Issues",
            "description":    "Users report slow and unhelpful support.",
            "sentiment":      "negative",
            "review_count":   13,
            "avg_rating":     1.8,
            "example_quotes": ["No response for 3 days", "Support is useless"],
        },
        {
            "theme_name":     "Good Experience",
            "description":    "Users praise overall app experience.",
            "sentiment":      "positive",
            "review_count":   63,
            "avg_rating":     4.5,
            "example_quotes": ["Love this app", "Best investment app"],
        },
    ]
}

GOOD_LLM_RESPONSE = json.dumps({
    "actions": [
        {
            "priority":         "P1",
            "category":         "Support",
            "title":            "Reduce customer support response time",
            "description":      "Implement SLA of 24h response. Hire 2 support agents.",
            "theme_source":     "Customer Support Issues",
            "effort":           "Medium",
            "expected_impact":  "Improve avg rating from 1.8 to 3.5 for support-related reviews.",
        },
        {
            "priority":         "P2",
            "category":         "Bug Fix",
            "title":            "Fix login and OTP flow bugs",
            "description":      "Reproducible crash on login. Fix OTP retry logic.",
            "theme_source":     "Technical Issues",
            "effort":           "Low",
            "expected_impact":  "Reduce 1-star technical reviews by ~30%.",
        },
    ]
})


def _write_inputs(tmpdir: str, run_label: str) -> None:
    """Write sample pulse.json and themes.json to tmpdir."""
    pulse_dir  = Path(tmpdir) / run_label / "04-pulse"
    themes_dir = Path(tmpdir) / run_label / "03-themes"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    themes_dir.mkdir(parents=True, exist_ok=True)
    (pulse_dir  / "pulse.json" ).write_text(json.dumps(SAMPLE_PULSE),      encoding="utf-8")
    (themes_dir / "themes.json").write_text(json.dumps(SAMPLE_THEMES_DOC), encoding="utf-8")


def _make_config(tmpdir: str) -> dict:
    return {
        "data_root": tmpdir,
        "llm": {
            "model_name":      "llama-3.3-70b-versatile",
            "api_key_env_var": "GROQ_API_KEY",
        },
    }


# ── Test cases ────────────────────────────────────────────────────────────────

class TestActionGenerator(unittest.TestCase):

    def test_idempotency_skips_api_if_output_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label   = "test-week"
            actions_dir = Path(tmpdir) / run_label / "05-actions"
            actions_dir.mkdir(parents=True)
            (actions_dir / "actions.json").write_text('{"actions": []}')

            cfg = _make_config(tmpdir)
            with patch("action_generator._call_groq") as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_not_called()

    def test_happy_path_writes_actions_json(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("action_generator._call_groq",
                       return_value=GOOD_LLM_RESPONSE) as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_called_once()

            actions_path = Path(tmpdir) / run_label / "05-actions" / "actions.json"
            self.assertTrue(actions_path.exists())
            output = json.loads(actions_path.read_text())

            for key in ["week_id", "generated_at", "model", "health_score",
                        "health_label", "action_count", "actions"]:
                self.assertIn(key, output, f"Missing key: {key}")

            self.assertEqual(output["week_id"], run_label)
            self.assertEqual(output["health_score"], 74)

    def test_actions_list_non_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("action_generator._call_groq", return_value=GOOD_LLM_RESPONSE):
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)

            output = json.loads(
                (Path(tmpdir) / run_label / "05-actions" / "actions.json").read_text()
            )
            self.assertGreater(len(output["actions"]), 0)
            self.assertEqual(output["action_count"], len(output["actions"]))

    def test_p1_action_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("action_generator._call_groq", return_value=GOOD_LLM_RESPONSE):
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)

            output  = json.loads(
                (Path(tmpdir) / run_label / "05-actions" / "actions.json").read_text()
            )
            p1_items = [a for a in output["actions"] if a.get("priority") == "P1"]
            self.assertGreater(len(p1_items), 0, "Expected at least one P1 action")
            for item in p1_items:
                for field in ["title", "description", "theme_source", "effort",
                              "expected_impact", "category"]:
                    self.assertIn(field, item, f"P1 action missing field: {field}")

    def test_missing_pulse_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            # Only write themes, not pulse
            run_label  = "test-week"
            themes_dir = Path(tmpdir) / run_label / "03-themes"
            themes_dir.mkdir(parents=True)
            (themes_dir / "themes.json").write_text(json.dumps(SAMPLE_THEMES_DOC))

            cfg = _make_config(tmpdir)
            with self.assertRaises(RuntimeError) as ctx:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
            self.assertIn("input not found", str(ctx.exception))

    def test_missing_themes_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            # Only write pulse, not themes
            run_label = "test-week"
            pulse_dir = Path(tmpdir) / run_label / "04-pulse"
            pulse_dir.mkdir(parents=True)
            (pulse_dir / "pulse.json").write_text(json.dumps(SAMPLE_PULSE))

            cfg = _make_config(tmpdir)
            with self.assertRaises(RuntimeError) as ctx:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
            self.assertIn("input not found", str(ctx.exception))

    def test_missing_api_key_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)
            env_clean = {k: v for k, v in __import__("os").environ.items()
                         if k != "GROQ_API_KEY"}
            with patch.dict("os.environ", env_clean, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("GROQ_API_KEY", str(ctx.exception))

    def test_bad_llm_response_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)
            with patch("action_generator._call_groq",
                       return_value="Not JSON at all."):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("parse", str(ctx.exception).lower())


class TestParseResponse(unittest.TestCase):

    def test_valid_json(self):
        result = _parse_response(GOOD_LLM_RESPONSE)
        self.assertIn("actions", result)
        self.assertEqual(len(result["actions"]), 2)

    def test_json_in_prose(self):
        prose  = f"Here is the action plan:\n\n{GOOD_LLM_RESPONSE}\n\nEnd."
        result = _parse_response(prose)
        self.assertIn("actions", result)

    def test_invalid_raises(self):
        with self.assertRaises(RuntimeError):
            _parse_response("Definitely not JSON")


if __name__ == "__main__":
    unittest.main(verbosity=2)
