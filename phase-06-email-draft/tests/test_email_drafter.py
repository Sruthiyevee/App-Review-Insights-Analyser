"""
test_email_drafter.py — Unit tests for Phase 06: Email Draft & Send
---------------------------------------------------------------------
All tests are fully offline — Groq and smtplib are mocked.

Test coverage:
  1.  Idempotency — skips if send_receipt.json exists (no Groq, no SMTP)
  2.  Happy path — one _call_groq, SMTP attempted, receipt written
  3.  Draft-only mode — receipt written with sent=False when SMTP creds missing
  4.  HTML draft file saved to disk
  5.  Missing pulse.json → RuntimeError
  6.  Missing actions.json → RuntimeError
  7.  Missing Groq API key → RuntimeError
  8.  Bad LLM JSON → RuntimeError
  9.  _parse_response — valid JSON
  10. _parse_response — JSON in prose
  11. _parse_response — invalid → RuntimeError
  12. HTML contains health score
  13. HTML contains all action titles
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_TESTS_DIR    = Path(__file__).resolve().parent
_PHASE_DIR    = _TESTS_DIR.parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from email_drafter import run, _parse_response, _build_html, _build_plaintext  # noqa: E402

NULL_LOGGER = logging.getLogger("test.null")
NULL_LOGGER.addHandler(logging.NullHandler())

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_PULSE = {
    "week_id": "test-week", "health_score": 74, "health_label": "Stable",
    "weighted_avg_rating": 3.7, "total_reviews": 133,
    "summary": "App is stable.", "pm_note": "Fix support.",
    "top_positives": ["Good Experience"], "top_negatives": ["Customer Support Issues"],
    "watch_list": ["App Interface"],
}

SAMPLE_ACTIONS_DOC = {
    "week_id": "test-week", "health_score": 74, "health_label": "Stable",
    "action_count": 2,
    "actions": [
        {"priority": "P1", "category": "Support", "title": "Improve Support", "effort": "Medium",
         "description": "Hire agents.", "theme_source": "Customer Support Issues",
         "expected_impact": "Better ratings."},
        {"priority": "P2", "category": "Bug Fix", "title": "Fix Login Bug", "effort": "Low",
         "description": "Fix OTP flow.", "theme_source": "Technical Issues",
         "expected_impact": "Fewer crashes."},
    ]
}

SAMPLE_THEMES = {
    "themes": [
        {"theme_name": "Support", "description": "Support issues.", "example_quotes": ["Quote 1"]},
        {"theme_name": "Bugs", "description": "Crash issues.", "example_quotes": ["Quote 2"]}
    ]
}

GOOD_LLM_DICT = {
    "executive_summary": "App health is stable at 74/100.",
    "top_themes": ["Support", "Login", "Performance"],
    "user_quotes": ["Quote A", "Quote B", "Quote C"],
    "top_actions": ["Action 1", "Action 2", "Action 3"]
}
GOOD_LLM_RESPONSE = json.dumps(GOOD_LLM_DICT)


def _write_inputs(tmpdir: str, run_label: str) -> None:
    for subdir, filename, content in [
        ("04-pulse",   "pulse.json",   SAMPLE_PULSE),
        ("05-actions", "actions.json", SAMPLE_ACTIONS_DOC),
        ("03-themes",  "themes.json",  SAMPLE_THEMES),
    ]:
        d = Path(tmpdir) / run_label / subdir
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(json.dumps(content), encoding="utf-8")


def _make_config(tmpdir: str, with_email: bool = False) -> dict:
    cfg = {
        "data_root": tmpdir,
        "llm": {"model_name": "llama-3.3-70b-versatile", "api_key_env_var": "GROQ_API_KEY"},
        "email": {
            "recipient":      "test@example.com",
            "sender_env_var": "EMAIL_SENDER",
            "password_env_var": "EMAIL_APP_PASSWORD",
            "smtp_host":      "smtp.gmail.com",
            "smtp_port":      587,
        },
    }
    return cfg


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEmailDrafter(unittest.TestCase):

    def test_idempotency_skips_all_if_receipt_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label  = "test-week"
            email_dir  = Path(tmpdir) / run_label / "06-email"
            email_dir.mkdir(parents=True)
            (email_dir / "send_receipt.json").write_text('{"sent": true}')

            cfg = _make_config(tmpdir)
            with patch("email_drafter._call_groq") as mock_groq, \
                 patch("email_drafter.smtplib.SMTP")  as mock_smtp:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_groq.assert_not_called()
                mock_smtp.assert_not_called()

    def test_happy_path_sends_email_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {
                 "GROQ_API_KEY": "test-key",
                 "EMAIL_SENDER": "sender@gmail.com",
                 "EMAIL_APP_PASSWORD": "abcdabcdabcdabcd",
             }):
            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("email_drafter._call_groq", return_value=GOOD_LLM_RESPONSE) as mock_groq, \
                 patch("email_drafter.smtplib.SMTP") as mock_smtp_cls:
                mock_smtp_instance = MagicMock()
                mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
                mock_smtp_cls.return_value.__exit__  = MagicMock(return_value=False)

                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_groq.assert_called_once()

            receipt = json.loads(
                (Path(tmpdir) / run_label / "06-email" / "send_receipt.json").read_text()
            )
            self.assertTrue(receipt["sent"])
            self.assertEqual(receipt["recipient"], "test@example.com")

    def test_draft_only_when_smtp_creds_missing(self):
        """If EMAIL_SENDER / EMAIL_APP_PASSWORD not set, save draft but don't send."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"},
                        clear=False):
            env_clean = {k: v for k, v in __import__("os").environ.items()
                         if k not in ("EMAIL_SENDER", "EMAIL_APP_PASSWORD")}
            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("email_drafter._call_groq", return_value=GOOD_LLM_RESPONSE), \
                 patch.dict("os.environ", env_clean, clear=True), \
                 patch("email_drafter.smtplib.SMTP") as mock_smtp:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                mock_smtp.assert_not_called()

            receipt = json.loads(
                (Path(tmpdir) / run_label / "06-email" / "send_receipt.json").read_text()
            )
            self.assertFalse(receipt["sent"])
            self.assertIn("reason", receipt)

    def test_html_draft_saved_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            env_clean = {k: v for k, v in __import__("os").environ.items()
                         if k not in ("EMAIL_SENDER", "EMAIL_APP_PASSWORD")}
            run_label = "test-week"
            _write_inputs(tmpdir, run_label)
            cfg = _make_config(tmpdir)

            with patch("email_drafter._call_groq", return_value=GOOD_LLM_RESPONSE), \
                 patch.dict("os.environ", env_clean, clear=True):
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)

            draft = Path(tmpdir) / run_label / "06-email" / "email_draft.html"
            self.assertTrue(draft.exists())
            self.assertGreater(draft.stat().st_size, 1000)

    def test_missing_pulse_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            run_label  = "test-week"
            actions_dir = Path(tmpdir) / run_label / "05-actions"
            actions_dir.mkdir(parents=True)
            (actions_dir / "actions.json").write_text(json.dumps(SAMPLE_ACTIONS_DOC))
            cfg = _make_config(tmpdir)
            with self.assertRaises(RuntimeError) as ctx:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
            self.assertIn("input not found", str(ctx.exception))

    def test_missing_actions_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            run_label = "test-week"
            pulse_dir = Path(tmpdir) / run_label / "04-pulse"
            pulse_dir.mkdir(parents=True)
            (pulse_dir / "pulse.json").write_text(json.dumps(SAMPLE_PULSE))
            cfg = _make_config(tmpdir)
            with self.assertRaises(RuntimeError) as ctx:
                run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
            self.assertIn("input not found", str(ctx.exception))

    def test_missing_groq_key_raises(self):
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
            with patch("email_drafter._call_groq", return_value="Not JSON at all."):
                with self.assertRaises(RuntimeError) as ctx:
                    run(week_id=run_label, config=cfg, logger=NULL_LOGGER)
                self.assertIn("parse", str(ctx.exception).lower())


class TestHTMLBuilder(unittest.TestCase):

    def test_html_contains_health_score(self):
        html = _build_html(SAMPLE_PULSE, SAMPLE_ACTIONS_DOC["actions"], GOOD_LLM_DICT)
        self.assertIn("74", html)
        self.assertIn("Stable", html)

    def test_html_contains_action_titles(self):
        html = _build_html(SAMPLE_PULSE, SAMPLE_ACTIONS_DOC["actions"], GOOD_LLM_DICT)
        self.assertIn("Improve Support", html)
        self.assertIn("Fix Login Bug", html)


class TestParseResponse(unittest.TestCase):

    def test_valid_json(self):
        result = _parse_response(GOOD_LLM_RESPONSE)
        self.assertIn("executive_summary", result)

    def test_json_in_prose(self):
        prose  = f"Here it is:\n\n{GOOD_LLM_RESPONSE}\n\nDone."
        result = _parse_response(prose)
        self.assertIn("executive_summary", result)

    def test_invalid_raises(self):
        with self.assertRaises(RuntimeError):
            _parse_response("Not JSON at all")


if __name__ == "__main__":
    unittest.main(verbosity=2)
