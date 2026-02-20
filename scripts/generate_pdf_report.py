from fpdf import FPDF
import json
from datetime import datetime

class WeeklyPulsePDF(FPDF):
    def header(self):
        self.set_fill_color(15, 16, 20) # Deep background
        self.rect(0, 0, 210, 297, "F")
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(255, 255, 255)
        self.cell(0, 20, "Weekly Product Health Pulse", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 12)
        self.set_text_color(148, 163, 184) # Slate
        self.cell(0, 10, "Period: Feb 09 - Feb 15, 2026 (W07) | Status: STABLE", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)

    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(124, 58, 237) # Violet
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def section_content(self, text):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(203, 213, 225) # Light grey
        self.multi_cell(0, 7, text)
        self.ln(5)

    def metric_box(self, label, value, color=(255, 255, 255)):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(148, 163, 184)
        self.cell(40, 6, label.upper())
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*color)
        self.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

def generate_report():
    pdf = WeeklyPulsePDF()
    pdf.add_page()

    # --- Executive Summary ---
    pdf.chapter_title("Executive Summary")
    summary = (
        "The app's health score remains stable at 74/100, with a weighted average rating of 3.7/5.0 based on 133 reviews. "
        "Users are generally having a good experience, but are facing issues with customer support and technical problems."
    )
    pdf.section_content(summary)
    
    # --- Metrics ---
    pdf.chapter_title("Key Performance Indicators")
    pdf.metric_box("Health Score", "74 / 100", (16, 185, 129)) # Emerald
    pdf.metric_box("Avg Rating", "3.70 / 5.0", (251, 191, 36)) # Amber
    pdf.metric_box("Review Volume", "133", (99, 102, 241)) # Indigo
    pdf.ln(5)

    # --- Themes ---
    pdf.chapter_title("Top Positives")
    pdf.section_content("- Good Experience (63 reviews)\n- Investment Features (11 reviews)\n- User Education (4 reviews)")

    pdf.chapter_title("Top Negatives")
    pdf.section_content("- Customer Support (1.8 rating)\n- Technical / MF Credit Issues (2.1 rating)\n- Withdrawal Difficulties")

    # --- Actions ---
    pdf.chapter_title("Priority Action Items")
    self_bold = pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(244, 63, 94) # Rose
    pdf.cell(0, 8, "P1: Improve Customer Support (High Effort)", new_x="LMARGIN", new_y="NEXT")
    pdf.section_content("Implement responsive support to address 'Zero contact Care' feedback.")
    
    pdf.cell(0, 8, "P1: Resolve Technical Feature Failures (Med Effort)", new_x="LMARGIN", new_y="NEXT")
    pdf.section_content("Fix Scan & Pay and MF credit syncing errors reported this week.")

    pdf.output("WEEKLY_PULSE_REPORT.pdf")
    print("PDF Generated: WEEKLY_PULSE_REPORT.pdf")

if __name__ == "__main__":
    generate_report()
