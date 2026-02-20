"""
test_history_archiver.py — Unit tests for Phase 07: Storage & History Registry
-------------------------------------------------------------------------------
All tests are fully offline — no LLM calls involved in Phase 07.

Test coverage:
  1.  Happy path (all 6 phases complete) — index.json created with correct record
  2.  latest.json written and matches newest run
  3.  Partial run (only phases 01–03) — partial record stored, no error
  4.  Multiple runs — index.json accumulates all runs
  5.  Idempotency — unchanged record skips write (updated_at stays the same)
  6.  Re-archive — changed artifact updates the record
  7.  No artifacts at all → RuntimeError
  8.  Existing index.json preserved when adding new run
  9.  Health score correctly extracted from pulse.json
  10. Email sent status correctly extracted from send_receipt.json
  11. Theme count correctly extracted from themes.json
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

_TESTS_DIR    = Path(__file__).resolve().parent
_PHASE_DIR    = _TESTS_DIR.parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from history_archiver import run  # noqa: E402

NULL_LOGGER = logging.getLogger("test.null")
NULL_LOGGER.addHandler(logging.NullHandler())


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_config(tmpdir: str) -> dict:
    return {"data_root": tmpdir}


def _write_raw(run_dir: Path, total: int = 200) -> None:
    d = run_dir / "01-raw"
    d.mkdir(parents=True, exist_ok=True)
    (d / "reviews_raw.json").write_text(
        json.dumps({"total_reviews": total, "reviews": []}), encoding="utf-8"
    )


def _write_clean(run_dir: Path, count: int = 150) -> None:
    d = run_dir / "02-clean"
    d.mkdir(parents=True, exist_ok=True)
    reviews = [{"id": str(i)} for i in range(count)]
    (d / "reviews_clean.json").write_text(json.dumps(reviews), encoding="utf-8")


def _write_themes(run_dir: Path, count: int = 10) -> None:
    d = run_dir / "03-themes"
    d.mkdir(parents=True, exist_ok=True)
    themes = [{"theme_name": f"Theme {i}"} for i in range(count)]
    (d / "themes.json").write_text(
        json.dumps({"themes": themes}), encoding="utf-8"
    )


def _write_pulse(run_dir: Path, score: int = 74, label: str = "Stable") -> None:
    d = run_dir / "04-pulse"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pulse.json").write_text(
        json.dumps({"health_score": score, "health_label": label,
                    "weighted_avg_rating": 3.7}),
        encoding="utf-8"
    )


def _write_actions(run_dir: Path, count: int = 7) -> None:
    d = run_dir / "05-actions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "actions.json").write_text(
        json.dumps({"action_count": count, "actions": []}), encoding="utf-8"
    )


def _write_receipt(run_dir: Path, sent: bool = True,
                   recipient: str = "test@example.com") -> None:
    d = run_dir / "06-email"
    d.mkdir(parents=True, exist_ok=True)
    (d / "send_receipt.json").write_text(
        json.dumps({"sent": sent, "recipient": recipient}), encoding="utf-8"
    )


def _write_all_phases(run_dir: Path) -> None:
    _write_raw(run_dir)
    _write_clean(run_dir)
    _write_themes(run_dir)
    _write_pulse(run_dir)
    _write_actions(run_dir)
    _write_receipt(run_dir)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHistoryArchiver(unittest.TestCase):

    def test_happy_path_creates_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            run_dir   = Path(tmpdir) / run_label
            _write_all_phases(run_dir)

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            index_path = Path(tmpdir) / "history" / "index.json"
            self.assertTrue(index_path.exists())
            index = json.loads(index_path.read_text())
            self.assertIn(run_label, index["runs"])
            record = index["runs"][run_label]
            self.assertEqual(record["run_label"], run_label)
            self.assertEqual(len(record["phases_complete"]), 6)

    def test_latest_json_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            _write_all_phases(Path(tmpdir) / run_label)

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            latest_path = Path(tmpdir) / "history" / "latest.json"
            self.assertTrue(latest_path.exists())
            latest = json.loads(latest_path.read_text())
            self.assertEqual(latest["run_label"], run_label)

    def test_partial_run_stored_without_error(self):
        """Only phases 01–03 complete — record is stored with available data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "partial-week"
            run_dir   = Path(tmpdir) / run_label
            _write_raw(run_dir)
            _write_clean(run_dir)
            _write_themes(run_dir)  # No phase 04/05/06

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            index = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            record = index["runs"][run_label]
            self.assertEqual(sorted(record["phases_complete"]), ["01", "02", "03"])
            self.assertIsNone(record["health_score"])  # Not yet available

    def test_multiple_runs_accumulate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for label in ["week-01", "week-02", "week-03"]:
                _write_all_phases(Path(tmpdir) / label)
                run(week_id=label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            index = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            self.assertEqual(len(index["runs"]), 3)
            for label in ["week-01", "week-02", "week-03"]:
                self.assertIn(label, index["runs"])

    def test_idempotency_skips_unchanged_record(self):
        """Running twice with unchanged artifacts should not update archived_at."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            _write_all_phases(Path(tmpdir) / run_label)

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)
            index1 = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            ts1 = index1["runs"][run_label]["archived_at"]

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)
            index2 = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            ts2 = index2["runs"][run_label]["archived_at"]

            # archived_at should be unchanged because record is identical
            self.assertEqual(ts1, ts2)

    def test_changed_artifact_updates_record(self):
        """Force a change (different health score) — should update the record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            run_dir   = Path(tmpdir) / run_label
            _write_all_phases(run_dir)
            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            # Update pulse with new health score
            _write_pulse(run_dir, score=55, label="At Risk")
            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            index = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            self.assertEqual(index["runs"][run_label]["health_score"], 55)
            self.assertEqual(index["runs"][run_label]["health_label"], "At Risk")

    def test_no_artifacts_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run(week_id="empty-week", config=_make_config(tmpdir), logger=NULL_LOGGER)
            self.assertIn("no phase artifacts", str(ctx.exception))

    def test_existing_index_preserved_when_adding_new_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # First run
            _write_all_phases(Path(tmpdir) / "week-01")
            run(week_id="week-01", config=_make_config(tmpdir), logger=NULL_LOGGER)

            # Second run
            _write_all_phases(Path(tmpdir) / "week-02")
            run(week_id="week-02", config=_make_config(tmpdir), logger=NULL_LOGGER)

            index = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            # Both runs should exist
            self.assertIn("week-01", index["runs"])
            self.assertIn("week-02", index["runs"])

    def test_health_score_extracted_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            run_dir   = Path(tmpdir) / run_label
            _write_raw(run_dir)
            _write_pulse(run_dir, score=88, label="Healthy")

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            index  = json.loads((Path(tmpdir) / "history" / "index.json").read_text())
            record = index["runs"][run_label]
            self.assertEqual(record["health_score"], 88)
            self.assertEqual(record["health_label"], "Healthy")

    def test_email_sent_status_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            run_dir   = Path(tmpdir) / run_label
            _write_raw(run_dir)
            _write_receipt(run_dir, sent=True, recipient="pm@company.com")

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            record = json.loads(
                (Path(tmpdir) / "history" / "index.json").read_text()
            )["runs"][run_label]
            self.assertTrue(record["email_sent"])
            self.assertEqual(record["email_recipient"], "pm@company.com")

    def test_theme_count_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_label = "test-week"
            run_dir   = Path(tmpdir) / run_label
            _write_raw(run_dir)
            _write_themes(run_dir, count=8)

            run(week_id=run_label, config=_make_config(tmpdir), logger=NULL_LOGGER)

            record = json.loads(
                (Path(tmpdir) / "history" / "index.json").read_text()
            )["runs"][run_label]
            self.assertEqual(record["theme_count"], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
