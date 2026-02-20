"""
email_sender.py — Phase 08: Email Dispatch
--------------------------------------------
Composes and sends the weekly executive email with PDF and HTML attachments.
Uses curated insights from Phase 06 and PDF from Phase 07.
"""

import json
import logging
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Any

# Path bootstrap
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    logger.info("Phase 08 — Email Dispatch: starting.")
    start = time.monotonic()

    data_root     = Path(config.get("data_root", "data"))
    insights_path = data_root / week_id / "06-insights" / "insights.json"
    pulse_path    = data_root / week_id / "04-pulse" / "pulse.json"
    pdf_path      = data_root / week_id / "07-pdf-report" / "WEEKLY_PULSE_REPORT.pdf"
    
    output_dir    = data_root / week_id / "08-email"
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path  = output_dir / "send_receipt.json"

    # Idempotency
    if receipt_path.exists():
        logger.info(f"  send_receipt.json exists — skipping. ({receipt_path})")
        return

    # Load inputs
    if not insights_path.exists() or not pulse_path.exists() or not pdf_path.exists():
        raise RuntimeError(f"Phase 08: Missing inputs for week {week_id}")

    with open(insights_path) as f: insights = json.load(f).get("insights", {})
    with open(pulse_path) as f: pulse = json.load(f)

    # ── Build email bodies ───────────────────────────────────────────────────
    # We use a simple but professional HTML body.
    # The user also wanted the HTML draft as an attachment? Usually, the email IS HTML.
    # I'll include a simple HTML body and attach the PDF + a "Report.html" copy if desired.
    html_body = _build_html_dispatch(pulse, insights)
    
    # Resolve config
    email_cfg = config.get("email", {})
    recipient    = email_cfg.get("recipient", "")
    sender_var   = email_cfg.get("sender_env_var", "EMAIL_SENDER")
    password_var = email_cfg.get("password_env_var", "EMAIL_APP_PASSWORD")
    sender       = os.environ.get(sender_var, "")
    password     = os.environ.get(password_var, "")

    if not sender or not password or not recipient:
        logger.warning("  Email credentials or recipient missing — skipping send.")
        _write_receipt(receipt_path, week_id, recipient, sent=False, reason="Missing config")
        return

    # ── Compose & Send ───────────────────────────────────────────────────────
    subject = f"[App Pulse] {week_id} - {pulse.get('health_label')} ({pulse.get('health_score')}/100)"
    
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient

    # HTML Body
    msg.attach(MIMEText(html_body, "html"))

    # Attachment: PDF
    with open(pdf_path, "rb") as f:
        pdf_attach = MIMEApplication(f.read(), _subtype="pdf")
        pdf_attach.add_header("Content-Disposition", "attachment", filename=f"Weekly_Pulse_{week_id}.pdf")
        msg.attach(pdf_attach)

    # Attachment: HTML Copy (as requested)
    html_attach = MIMEText(html_body, "html")
    html_attach.add_header("Content-Disposition", "attachment", filename="Executive_Pulse.html")
    msg.attach(html_attach)

    logger.info(f"  Sending email to {recipient} with 2 attachments...")
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info("  Email sent successfully.")
        _write_receipt(receipt_path, week_id, recipient, sent=True)
    except Exception as e:
        logger.error(f"  Failed to send email: {e}")
        _write_receipt(receipt_path, week_id, recipient, sent=False, reason=str(e))

    elapsed = time.monotonic() - start
    logger.info(f"Phase 08 — Email Dispatch: complete in {elapsed:.1f}s.")

def _build_html_dispatch(pulse: dict, insights: dict) -> str:
    week_id = pulse.get("week_id")
    score = pulse.get("health_score")
    label = pulse.get("health_label")
    
    themes_li = "".join(f"<li>{t['name']}</li>" for t in insights.get("top_themes", []))
    quotes_li = "".join(f"<li style='font-style:italic;'>\"{q}\"</li>" for q in insights.get("top_quotes", []))
    actions_li = "".join(f"<li><b>{a['title']}</b>: {a['description']}</li>" for a in insights.get("top_actions", []))

    return f"""
    <html>
    <body style="font-family:sans-serif; color:#1e293b; line-height:1.5;">
        <div style="background:#1e40af; color:white; padding:20px; border-radius:8px 8px 0 0;">
            <h1 style="margin:0;">Weekly Product Pulse — {week_id}</h1>
        </div>
        <div style="padding:20px; border:1px solid #e5e7eb; border-radius:0 0 8px 8px;">
            <div style="margin-bottom:20px;">
                <p style="font-size:48px; font-weight:bold; margin:0; color:#1e40af;">{score}</p>
                <p style="text-transform:uppercase; font-weight:bold; margin:0; color:#64748b;">Health Status: {label}</p>
            </div>
            
            <h2 style="color:#1e40af; border-bottom:1px solid #e5e7eb; padding-bottom:5px;">Top 3 Themes</h2>
            <ul>{themes_li}</ul>
            
            <h2 style="color:#1e40af; border-bottom:1px solid #e5e7eb; padding-bottom:5px;">Top 3 User Quotes</h2>
            <ul>{quotes_li}</ul>
            
            <h2 style="color:#1e40af; border-bottom:1px solid #e5e7eb; padding-bottom:5px;">Top 3 Priority Actions</h2>
            <ul>{actions_li}</ul>
            
            <p style="margin-top:30px; font-size:12px; color:#64748b;">
                * Please see full detailed attachments (PDF & HTML) for depth.
            </p>
        </div>
    </body>
    </html>
    """

def _write_receipt(path, week_id, recipient, sent, reason=""):
    receipt = {
        "week_id": week_id,
        "sent": sent,
        "recipient": recipient,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "reason": reason
    }
    with open(path, "w") as f: json.dump(receipt, f, indent=2)

if __name__ == "__main__":
    import yaml
    from dotenv import load_dotenv
    load_dotenv()
    with open(_PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml") as f:
        cfg = yaml.safe_load(f)
    _logging = logging.getLogger("test")
    _logging.setLevel(logging.INFO)
    _logging.addHandler(logging.StreamHandler())
    run(week_id="historical-12w", config=cfg, logger=_logging)
