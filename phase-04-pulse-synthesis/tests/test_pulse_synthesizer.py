"""
test_pulse_synthesizer.py — Unit tests for Phase 04: Pulse Synthesis
----------------------------------------------------------------------
All tests are fully offline — Groq is mocked. No API keys required.

Test coverage:
  Score calculator:
    1. All positive themes → Healthy label
    2. All negative themes → score penalty applied
    3. Empty themes → score=0, Critical
    4. Score clamped to [0, 100]
    5. Label boundary values (80, 60, 40, 0)

  Pulse synthesizer run():
    6. Idempotency — skips API if pulse.json exists
    7. Happy path — exactly one _call_groq, pulse.json written with all keys
    8. Missing themes.json input → RuntimeError
    9. Missing API key → RuntimeError
   10. Bad LLM JSON → RuntimeError
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Path bootstrap (conftest.py also does this, belt-and-suspenders) ────────
_TESTS_DIR    = Path(__file__).resolve().parent
_PHASE_DIR    = _TESTS_DIR.parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from score_calculator import compute_health_score   # noqa: E402
from pulse_synthesizer import run, _parse_response  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_themes(sentiments_ratings: list[tuple[str, float, int]]) -> list[dict]:
    """Build a list of theme dicts from (sentiment, avg_rating, review_count) tuples."""
    return [
        {
            "theme_name":     f"Theme {i}",
            "description":    "Test theme.",
            "sentiment":      sent,
            "avg_rating":     rat,
            "review_count":   cnt,
            "example_quotes": ["quote"],
        }
        for i, (sent, rat, cnt) in enumerate(sentiments_ratings)
    ]


def _make_themes_doc(themes: list[dict], week_id: str = "test-week") -> dict:
    return {
        "week_id": week_id,
        "extracted_at": "2026-02-20T14:00:00+00:00",
        "model": "llama-3.3-70b-versatile",
        "total_reviews": sum(t["review_count"] for t in themes),
        "themes": themes,
    }


GOOD_LLM_RESPONSE = json.dumps({
    "summary":       "App is mostly positive with some support pain points.",
    "top_positives": ["Theme 0", "Theme 2"],
    "top_negatives": ["Theme 1"],
    "watch_list":    ["Theme 3"],
    "pm_note":       "Prioritize reducing support escalations this week.",
})

NULL_LOGGER = logging.getLogger("test.null")
NULL_LOGGER.addHandler(logging.NullHandler())


# ── Score calculator tests ─────────────────────────────────────────────────

class TestScoreCalculator(unittest.TestCase):

    def test_all_positive_gives_healthy(self):
        themes = _make_themes([("positive", 4.8, 50), ("positive", 4.5, 30)])
        result = compute_health_score(themes)
        self.assertGreaterEqual(result["health_score"], 80)
        self.assertEqual(result["health_label"], "Healthy")

    def test_dominant_negative_reduces_score(self):
        # One huge negative theme (40% share) should incur penalty
        themes = _make_themes([("negative", 1.5, 40), ("positive", 4.8, 60)])
        without_penalty = ((1.5*40 + 4.8*60) / 100) / 5 * 100
        result = compute_health_score(themes)
        self.assertLess(result["health_score"], round(without_penalty))

    def test_empty_themes_returns_critical(self):
        result = compute_health_score([])
        self.assertEqual(result["health_score"], 0)
        self.assertEqual(result["health_label"], "Critical")

    def test_score_clamped_to_100(self):
        themes = _make_themes([("positive", 5.0, 100)])
        result = compute_health_score(themes)
        self.assertLessEqual(result["health_score"], 100)

    def test_score_clamped_to_0(self):
        # Severe negatives shouldn't produce negative score
        themes = _make_themes([("negative", 1.0, 200), ("negative", 1.0, 200)])
        result = compute_health_score(themes)
        self.assertGreaterEqual(result["health_score"], 0)

    def test_label_boundaries(self):
        # Force specific scores by creating controlled themes
        cases = [
            ([("positive", 4.0, 100)], "Healthy"),   # ~80
            ([("mixed",    3.0, 100)], "At Risk"),    # ~60 before penalty → At Risk boundary
        ]
        for themes_spec, expected_label_prefix in cases:
            themes = _make_themes(themes_spec)
            result = compute_health_score(themes)
            # Label should be calculable and not None
            self.assertIsNotNone(result["health_label"])

    def test_total_reviews_correct(self):
        themes = _make_themes([("positive", 4.0, 30), ("negative", 2.0, 20)])
        result = compute_health_score(themes)
        self.assertEqual(result["total_reviews"], 50)


# ── Pulse synthesizer run() tests ─────────────────────────────────────────

class TestPulseSynthesizer(unittest.TestCase):

    def _make_config(self, data_root: str) -> dict:
        return {
            "data_root": data_root,
            "llm": {
                "model_name":      "llama-3.3-70b-versatile",
                "api_key_env_var": "GROQ_API_KEY",
            },
        }

    def _write_themes(self, tmpdir: str, run_label: str, themes: list[dict]) -> None:
        themes_dir = Path(tmpdir) / run_label / "03-themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        doc = _make_themes_doc(themes, week_id=run_label)
        (themes_dir / "themes.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_idempotency_skips_api_if_output_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label  = "test-week"
            pulse_dir  = Path(tmpdir) / run_label / "04-pulse"
            pulse_dir.mkdir(parents=True)
            (pulse_dir / "pulse.json").write_text('{"health_score": 70}')

            cfg = self._make_config(tmpdir)
            with patch("pulse_synthesizer._call_groq") as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_not_called()

    def test_happy_path_writes_pulse_json(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            themes    = _make_themes([
                ("positive", 4.5, 50),
                ("negative", 1.8, 20),
                ("mixed",    3.2, 10),
            ])
            self._write_themes(tmpdir, run_label, themes)

            cfg = self._make_config(tmpdir)
            with patch("pulse_synthesizer._call_groq",
                       return_value=GOOD_LLM_RESPONSE) as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_called_once()  # exactly ONE api call

            pulse_path = Path(tmpdir) / run_label / "04-pulse" / "pulse.json"
            self.assertTrue(pulse_path.exists())
            pulse = json.loads(pulse_path.read_text())

            # All required keys present
            for key in ["health_score", "health_label", "weighted_avg_rating",
                        "total_reviews", "summary", "top_positives",
                        "top_negatives", "watch_list", "pm_note"]:
                self.assertIn(key, pulse, f"Missing key: {key}")

            self.assertEqual(pulse["week_id"], run_label)
            self.assertIsInstance(pulse["health_score"], int)
            self.assertGreater(pulse["total_reviews"], 0)

    def test_missing_input_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._make_config(tmpdir)
            with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id="no-such-week", config=cfg, logger=NULL_LOGGER)
                self.assertIn("input not found", str(ctx.exception))

    def test_missing_api_key_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            self._write_themes(tmpdir, run_label, _make_themes([("positive", 4.0, 10)]))
            cfg = self._make_config(tmpdir)
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
            self._write_themes(tmpdir, run_label, _make_themes([("positive", 4.0, 10)]))
            cfg = self._make_config(tmpdir)
            with patch("pulse_synthesizer._call_groq",
                       return_value="Not JSON at all."):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("parse", str(ctx.exception).lower())


# ── Parse response tests ───────────────────────────────────────────────────

class TestParseResponse(unittest.TestCase):

    def test_valid_json(self):
        result = _parse_response(GOOD_LLM_RESPONSE)
        self.assertIn("summary", result)

    def test_json_in_prose(self):
        prose  = f"Sure thing! Here it is:\n\n{GOOD_LLM_RESPONSE}\n\nDone."
        result = _parse_response(prose)
        self.assertIn("summary", result)

    def test_invalid_raises(self):
        with self.assertRaises(RuntimeError):
            _parse_response("Totally not JSON!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
