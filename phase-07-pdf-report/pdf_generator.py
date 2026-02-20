"""
pdf_generator.py — Phase 07: PDF Generation
--------------------------------------------
Generates a professional one-page executive PDF report using the 
curated insights from Phase 06.
"""

import json
import logging
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fpdf import FPDF

# Path bootstrap
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

class WeeklyPulsePDF(FPDF):
    def __init__(self, week_id, health_score, health_label):
        super().__init__()
        self.week_id = week_id
        self.health_score = health_score
        self.health_label = health_label

    def header(self):
        # Deep Dark Background
        self.set_fill_color(15, 16, 20)
        self.rect(0, 0, 210, 297, "F")
        
        # Header Title
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(255, 255, 255)
        self.cell(0, 20, "Weekly Product Health Pulse", align="C", new_x="LMARGIN", new_y="NEXT")
        
        # Subtitle
        self.set_font("Helvetica", "", 12)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, f"Week: {self.week_id} | Status: {self.health_label.upper()}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)

    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(124, 58, 237) # Violet
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def section_content(self, text, is_quote=False):
        if is_quote:
            self.set_font("Helvetica", "I", 11)
            self.set_text_color(148, 163, 184) # Slate
        else:
            self.set_font("Helvetica", "", 11)
            self.set_text_color(203, 213, 225) # Light grey
        
        self.multi_cell(0, 7, text)
        self.ln(4)

    def metric_box(self, label, value, color=(255, 255, 255)):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(148, 163, 184)
        self.cell(40, 6, label.upper())
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*color)
        self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    logger.info("Phase 07 — PDF Generation: starting.")
    start = time.monotonic()

    data_root     = Path(config.get("data_root", "data"))
    insights_path = data_root / week_id / "06-insights" / "insights.json"
    pulse_path    = data_root / week_id / "04-pulse" / "pulse.json"
    output_dir    = data_root / week_id / "07-pdf-report"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_pdf    = output_dir / "WEEKLY_PULSE_REPORT.pdf"

    # Idempotency
    if report_pdf.exists():
        logger.info(f"  PDF report already exists. ({report_pdf})")
        return

    # Load inputs
    if not insights_path.exists() or not pulse_path.exists():
        raise RuntimeError(f"Phase 07: Missing inputs for week {week_id}")

    with open(insights_path) as f: insights = json.load(f).get("insights", {})
    with open(pulse_path) as f: pulse = json.load(f)

    # Initialize PDF
    pdf = WeeklyPulsePDF(
        week_id=week_id,
        health_score=pulse.get("health_score", 0),
        health_label=pulse.get("health_label", "Unknown")
    )
    pdf.add_page()

    # --- Metrics ---
    pdf.chapter_title("Key Performance Indicators")
    pdf.metric_box("Health Score", f"{pulse.get('health_score')}/100", (16, 185, 129))
    pdf.metric_box("Avg Rating", f"{pulse.get('weighted_avg_rating')} / 5.0", (251, 191, 36))
    pdf.metric_box("Total Reviews", pulse.get('total_reviews'), (99, 102, 241))
    pdf.ln(5)

    # --- Top 3 Themes ---
    pdf.chapter_title("Top 3 User Themes")
    for t in insights.get("top_themes", []):
        theme_text = f"[{t.get('sentiment','').upper()}] {t.get('name')}: {t.get('description')}"
        pdf.section_content(theme_text)

    # --- Top 3 Quotes ---
    pdf.chapter_title("Top 3 User Quotes")
    for q in insights.get("top_quotes", []):
        pdf.section_content(f"\"{q}\"", is_quote=True)

    # --- Top 3 Actions ---
    pdf.chapter_title("Top 3 Priority Actions")
    for a in insights.get("top_actions", []):
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(244, 63, 94) # Rose
        pdf.cell(0, 8, f"[{a.get('priority')}] {a.get('title')}", new_x="LMARGIN", new_y="NEXT")
        pdf.section_content(a.get('description', ''))

    # Save
    pdf.output(str(report_pdf))
    logger.info(f"  PDF report generated -> {report_pdf}")

    elapsed = time.monotonic() - start
    logger.info(f"Phase 07 — PDF Generation: complete in {elapsed:.1f}s.")

if __name__ == "__main__":
    # Test stub
    import yaml
    with open(_PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml") as f:
        cfg = yaml.safe_load(f)
    _logging = logging.getLogger("test")
    _logging.setLevel(logging.INFO)
    _logging.addHandler(logging.StreamHandler())
    run(week_id="historical-12w", config=cfg, logger=_logging)
