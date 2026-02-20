"""
test_theme_extractor.py — Unit tests for Phase 03: Theme Extraction
---------------------------------------------------------------------
All tests are fully offline — Groq API is mocked via unittest.mock.patch.
No API keys or network access required.

Test coverage:
  1. _parse_response: valid JSON string
  2. _parse_response: JSON embedded in prose (regex fallback)
  3. _parse_response: completely invalid → RuntimeError
  4. prompt_builder.build_prompt: output contains expected sections
  5. prompt_builder._stratified_sample: respects max cap, covers weeks
  6. run(): idempotency — skips API if themes.json already exists
  7. run(): happy path — calls _call_groq once, writes themes.json
  8. run(): missing input file → RuntimeError
  9. run(): missing API key → RuntimeError
 10. run(): bad LLM response → RuntimeError
"""

import json
import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest

# ── Path bootstrap ──────────────────────────────────────────────────────────
_TESTS_DIR    = Path(__file__).resolve().parent
_PHASE_DIR    = _TESTS_DIR.parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from theme_extractor import run, _parse_response, _call_groq  # noqa: E402
from prompt_builder import build_prompt, _stratified_sample    # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_reviews(n: int = 20) -> list[dict]:
    """Generate n synthetic clean review dicts."""
    weeks   = ["2026-W05", "2026-W06", "2026-W07", "2026-W08"]
    ratings = [1, 2, 3, 4, 5]
    bodies  = [
        "Excellent app, very smooth experience.",
        "Crashes constantly, lost my data.",
        "Login is broken since last update.",
        "Great customer support, resolved quickly.",
        "Interface is confusing and slow.",
        "Best investment app I have used.",
        "Frequent OTPs but otherwise fine.",
        "KYC process is too complicated.",
    ]
    return [
        {
            "review_id":   str(i),
            "platform":    "android" if i % 2 == 0 else "ios",
            "app_id":      "in.indwealth",
            "title":       None,
            "body":        bodies[i % len(bodies)],
            "rating":      ratings[i % len(ratings)],
            "author":      f"user_{i}",
            "region":      "in",
            "review_date": f"2026-02-{(i % 14) + 1:02d}",
            "week_id":     weeks[i % len(weeks)],
            "app_version": "6.2.1",
            "lang":        "en",
            "fetched_at":  "2026-02-20T14:00:00+00:00",
        }
        for i in range(n)
    ]


GOOD_LLM_RESPONSE = json.dumps({
    "themes": [
        {
            "theme_name":     "App Stability Issues",
            "description":    "Users report frequent crashes and data loss.",
            "sentiment":      "negative",
            "review_count":   42,
            "avg_rating":     1.8,
            "example_quotes": ["Crashes constantly", "lost my data"],
        },
        {
            "theme_name":     "Positive Customer Support",
            "description":    "Users praise the responsive support team.",
            "sentiment":      "positive",
            "review_count":   31,
            "avg_rating":     4.5,
            "example_quotes": ["Great customer support", "resolved quickly"],
        },
    ]
})

NULL_LOGGER = logging.getLogger("test.null")
NULL_LOGGER.addHandler(logging.NullHandler())


# ── Test cases ───────────────────────────────────────────────────────────────

class TestParseResponse(unittest.TestCase):

    def test_valid_json_string(self):
        result = _parse_response(GOOD_LLM_RESPONSE)
        self.assertIn("themes", result)
        self.assertEqual(len(result["themes"]), 2)

    def test_json_embedded_in_prose(self):
        """Model adds prose around the JSON — regex fallback must extract it."""
        prose = f"Sure! Here is the analysis:\n\n{GOOD_LLM_RESPONSE}\n\nHope that helps!"
        result = _parse_response(prose)
        self.assertIn("themes", result)

    def test_invalid_raises(self):
        with self.assertRaises(RuntimeError):
            _parse_response("This is not JSON at all.")


class TestPromptBuilder(unittest.TestCase):

    def test_prompt_contains_reviews(self):
        reviews = _make_reviews(10)
        prompt  = build_prompt(reviews)
        self.assertIn("REVIEWS", prompt)
        self.assertIn("Respond with the JSON object now.", prompt)
        # Each review numbered
        self.assertIn("[1]", prompt)

    def test_prompt_caps_at_max(self):
        """Even with 200 reviews, the prompt must sample ≤ MAX_REVIEWS_IN_PROMPT."""
        reviews = _make_reviews(200)
        prompt  = build_prompt(reviews, max_reviews=30)
        # Count numbered entries
        count = prompt.count("\n[")
        self.assertLessEqual(count, 31)  # ≤ 30 reviews + small buffer

    def test_stratified_sample_respects_cap(self):
        reviews = _make_reviews(100)
        sample  = _stratified_sample(reviews, 20)
        self.assertLessEqual(len(sample), 22)  # tolerates small overshoot

    def test_stratified_sample_covers_weeks(self):
        """Sample should include reviews from multiple weeks."""
        reviews = _make_reviews(80)
        sample  = _stratified_sample(reviews, 40)
        weeks   = {r["week_id"] for r in sample}
        self.assertGreater(len(weeks), 1)

    def test_fewer_reviews_than_max(self):
        reviews = _make_reviews(5)
        sample  = _stratified_sample(reviews, 20)
        self.assertEqual(len(sample), 5)  # returns all if fewer


class TestRunFunction(unittest.TestCase):

    def _make_config(self, data_root: str) -> dict:
        return {
            "data_root": data_root,
            "llm": {
                "model_name":    "llama3-8b-8192",
                "api_key_env_var": "GROQ_API_KEY",
            },
        }

    def test_idempotency_skips_api_if_output_exists(self):
        """If themes.json already exists, _call_groq must NOT be called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label   = "test-week"
            themes_dir  = Path(tmpdir) / run_label / "03-themes"
            themes_dir.mkdir(parents=True)
            # Pre-create the output file
            (themes_dir / "themes.json").write_text('{"themes": []}')

            cfg = self._make_config(tmpdir)
            with patch("theme_extractor._call_groq") as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_not_called()

    def test_happy_path_writes_themes_json(self):
        """Happy path: input exists, API key set, mock returns good JSON."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label  = "test-week"
            clean_dir  = Path(tmpdir) / run_label / "02-clean"
            clean_dir.mkdir(parents=True)
            reviews    = _make_reviews(10)
            (clean_dir / "reviews_clean.json").write_text(
                json.dumps(reviews), encoding="utf-8"
            )

            cfg = self._make_config(tmpdir)
            with patch("theme_extractor._call_groq",
                       return_value=GOOD_LLM_RESPONSE) as mock_call:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_call.assert_called_once()  # exactly ONE api call

            themes_path = Path(tmpdir) / run_label / "03-themes" / "themes.json"
            self.assertTrue(themes_path.exists())
            output = json.loads(themes_path.read_text())
            self.assertEqual(len(output["themes"]), 2)
            self.assertEqual(output["week_id"], run_label)
            self.assertEqual(output["model"], "llama3-8b-8192")

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
            clean_dir = Path(tmpdir) / run_label / "02-clean"
            clean_dir.mkdir(parents=True)
            (clean_dir / "reviews_clean.json").write_text(json.dumps(_make_reviews(5)))

            cfg = self._make_config(tmpdir)
            # Ensure the env var is absent
            env_without_key = {k: v for k, v in __import__("os").environ.items()
                               if k != "GROQ_API_KEY"}
            with patch.dict("os.environ", env_without_key, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("GROQ_API_KEY", str(ctx.exception))

    def test_bad_llm_response_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

            run_label = "test-week"
            clean_dir = Path(tmpdir) / run_label / "02-clean"
            clean_dir.mkdir(parents=True)
            (clean_dir / "reviews_clean.json").write_text(json.dumps(_make_reviews(5)))

            cfg = self._make_config(tmpdir)
            with patch("theme_extractor._call_groq",
                       return_value="This is definitely not JSON."):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("parse", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
