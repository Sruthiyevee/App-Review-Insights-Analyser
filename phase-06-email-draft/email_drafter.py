"""
email_drafter.py — Phase 06: Email Draft & Send
-------------------------------------------------
Generates a polished weekly Product Health Pulse email and sends it via
Gmail SMTP.

Pipeline:
  1. Load pulse.json (Phase 04) + actions.json (Phase 05).
  2. Build structured HTML email locally (no LLM needed for layout).
  3. Make ONE Groq API call to write a professional plain-text executive
     summary paragraph (the opening of the email).
  4. Compose the full HTML + plain-text email.
  5. Send via Gmail SMTP (smtplib + STARTTLS).
  6. Write email_draft.html and send_receipt.json to 06-email/.

API call guarantee:
  - Idempotency: if send_receipt.json exists, skip everything (no API, no SMTP).
  - Exactly ONE Groq call to generate the executive summary.
  - SMTP send happens only once per run.

Gmail requirements (user must set up):
  - 2-Step Verification ON for the sender Gmail account.
  - A 16-character App Password generated at:
    https://myaccount.google.com/apppasswords
  - EMAIL_SENDER and EMAIL_APP_PASSWORD set in .env
"""

import json
import logging
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

# Path bootstrap
_PHASE_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _PHASE_DIR.parent
for _p in [str(_PROJECT_ROOT), str(_PHASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# LLM prompt — executive summary only
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior product manager writing a concise executive summary for a weekly email.

**Output rules:**
- Respond with ONLY valid JSON. No markdown fences.
- Required JSON keys:
    "executive_summary": a 2-3 sentence overview of the project health.
    "top_themes": list of strings (exactly 3 most impactful themes).
    "user_quotes": list of strings (exactly 3 punchy, representative quotes).
    "top_actions": list of strings (exactly 3 most critical next steps).
- Tone: professional, punchy, and data-informed.
"""

def _build_summary_prompt(pulse: dict, actions: list[dict], themes: list[dict]) -> str:
    p1_actions = [a["title"] for a in actions if a.get("priority") == "P1"]
    theme_context = []
    for t in themes[:5]: # top 5 themes for context
        theme_context.append(f"- {t.get('theme_name')}: {t.get('description')} (Quotes: {t.get('example_quotes', [])[:2]})")
    
    return (
        f"Week: {pulse.get('week_id')}\n"
        f"Health Score: {pulse.get('health_score')}/100 ({pulse.get('health_label')})\n"
        f"Overall Summary: {pulse.get('summary')}\n"
        f"Top Themes Context:\n" + "\n".join(theme_context) + "\n"
        f"Available Actions: {', '.join([a['title'] for a in actions[:6]])}\n\n"
        "Generate the JSON with executive_summary, top_themes, user_quotes, and top_actions now."
    )


# ---------------------------------------------------------------------------
# HTML email template
# ---------------------------------------------------------------------------

def _build_html(pulse: dict, actions_list: list[dict], parsed_llm: dict) -> str:
    health_score = pulse.get("health_score", 0)
    health_label = pulse.get("health_label", "Unknown")
    week_id      = pulse.get("week_id", "")
    
    exec_summary = parsed_llm.get("executive_summary", "")
    top_themes   = parsed_llm.get("top_themes", [])
    user_quotes  = parsed_llm.get("user_quotes", [])
    top_actions  = parsed_llm.get("top_actions", [])

    # Score colour
    if health_score >= 80:
        score_color = "#22c55e"   # green
    elif health_score >= 60:
        score_color = "#f59e0b"   # amber
    elif health_score >= 40:
        score_color = "#ef4444"   # red
    else:
        score_color = "#7f1d1d"   # dark red

    # Actions rows (full table) - Strictly limited to top 3
    priority_badge = {"P1": "#ef4444", "P2": "#f59e0b", "P3": "#6b7280"}
    action_rows = ""
    for a in actions_list[:3]:
        badge_color = priority_badge.get(a.get("priority", "P3"), "#6b7280")
        action_rows += f"""
        <tr>
          <td style="padding:8px 12px;vertical-align:top;">
            <span style="background:{badge_color};color:#fff;padding:2px 8px;
                         border-radius:4px;font-size:11px;font-weight:bold;">
              {a.get('priority','?')}
            </span>
          </td>
          <td style="padding:8px 12px;font-weight:600;vertical-align:top;">{a.get('title','')}</td>
          <td style="padding:8px 12px;color:#6b7280;vertical-align:top;">{a.get('category','')}</td>
          <td style="padding:8px 12px;color:#6b7280;vertical-align:top;">{a.get('effort','')}</td>
          <td style="padding:8px 12px;font-size:13px;vertical-align:top;">{a.get('description','')}</td>
        </tr>"""

    themes_li = "".join(f"<li>{t}</li>" for t in top_themes)
    quotes_li = "".join(f"<li style='margin-bottom:8px;font-style:italic;'>\"{q}\"</li>" for q in user_quotes)
    top_actions_li = "".join(f"<li><b>{a}</b></li>" for a in top_actions)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>App Review Pulse — {week_id}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:12px;overflow:hidden;
              box-shadow:0 4px 24px rgba(0,0,0,0.08);">

  <!-- Header -->
  <tr style="background:linear-gradient(135deg,#1e40af,#3b82f6);">
    <td style="padding:28px 32px;">
      <p style="margin:0;color:#bfdbfe;font-size:13px;letter-spacing:1px;">
        WEEKLY PRODUCT HEALTH PULSE
      </p>
      <h1 style="margin:6px 0 0;color:#ffffff;font-size:24px;">{week_id}</h1>
    </td>
  </tr>

  <!-- Score banner -->
  <tr>
    <td style="padding:24px 32px;border-bottom:1px solid #e5e7eb;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="margin:0;color:#6b7280;font-size:13px;">HEALTH SCORE</p>
            <p style="margin:4px 0 0;font-size:48px;font-weight:bold;
                      color:{score_color};">{health_score}</p>
            <p style="margin:2px 0 0;color:{score_color};font-weight:600;">
              {health_label}
            </p>
          </td>
          <td style="text-align:right;vertical-align:top;">
            <p style="margin:0;color:#6b7280;font-size:13px;">AVG RATING</p>
            <p style="margin:4px 0 0;font-size:32px;font-weight:bold;color:#1e293b;">
              {pulse.get('weighted_avg_rating','?')} ★
            </p>
            <p style="margin:2px 0 0;color:#6b7280;font-size:13px;">
              from {pulse.get('total_reviews','?')} reviews
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Executive Summary -->
  <tr>
    <td style="padding:24px 32px;border-bottom:1px solid #e5e7eb;">
      <h2 style="margin:0 0 12px;font-size:16px;color:#1e293b;">Executive Summary</h2>
      <p style="margin:0;color:#374151;line-height:1.7;font-size:14px;">{exec_summary}</p>
    </td>
  </tr>

  <!-- Refined Highlights: Themes, Quotes, Actions -->
  <tr>
    <td style="padding:24px 32px;border-bottom:1px solid #e5e7eb;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="50%" style="vertical-align:top;padding-right:20px;">
            <h3 style="margin:0 0 10px;font-size:13px;color:#1e40af;text-transform:uppercase;">Top 3 Themes</h3>
            <ul style="margin:0;padding-left:18px;color:#374151;font-size:13px;line-height:1.6;">{themes_li}</ul>
          </td>
          <td width="50%" style="vertical-align:top;">
            <h3 style="margin:0 0 10px;font-size:13px;color:#1e40af;text-transform:uppercase;">3 Action Ideas</h3>
            <ul style="margin:0;padding-left:18px;color:#374151;font-size:13px;line-height:1.6;">{top_actions_li}</ul>
          </td>
        </tr>
      </table>
      <div style="margin-top:20px;padding:16px;background:#f9fafb;border-left:4px solid #3b82f6;border-radius:4px;">
        <h3 style="margin:0 0 10px;font-size:13px;color:#1e40af;text-transform:uppercase;">3 User Quotes</h3>
        <ul style="margin:0;padding-left:18px;color:#4b5563;font-size:13px;line-height:1.6;">{quotes_li}</ul>
      </div>
    </td>
  </tr>

  <!-- Pulse Signals (Mini) -->
  <tr>
    <td style="padding:20px 32px;border-bottom:1px solid #e5e7eb;background:#fcfcfc;">
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;">
        <div style="margin-right:20px;">
          <p style="margin:0;font-size:11px;font-weight:bold;color:#22c55e;">STRENGTHS</p>
          <p style="margin:4px 0 0;font-size:12px;color:#4b5563;">{", ".join(pulse.get("top_positives",[]))}</p>
        </div>
        <div style="margin-right:20px;">
          <p style="margin:0;font-size:11px;font-weight:bold;color:#ef4444;">PAIN POINTS</p>
          <p style="margin:4px 0 0;font-size:12px;color:#4b5563;">{", ".join(pulse.get("top_negatives",[]))}</p>
        </div>
        <div>
          <p style="margin:0;font-size:11px;font-weight:bold;color:#f59e0b;">WATCH LIST</p>
          <p style="margin:4px 0 0;font-size:12px;color:#4b5563;">{", ".join(pulse.get("watch_list",[]))}</p>
        </div>
      </div>
    </td>
  </tr>

  <!-- Action Items -->
  <tr>
    <td style="padding:24px 32px;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#1e293b;">Action Items</h2>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;
                    font-size:13px;">
        <tr style="background:#f9fafb;">
          <th style="padding:10px 12px;text-align:left;color:#6b7280;font-weight:600;">
            Priority</th>
          <th style="padding:10px 12px;text-align:left;color:#6b7280;font-weight:600;">
            Action</th>
          <th style="padding:10px 12px;text-align:left;color:#6b7280;font-weight:600;">
            Category</th>
          <th style="padding:10px 12px;text-align:left;color:#6b7280;font-weight:600;">
            Effort</th>
          <th style="padding:10px 12px;text-align:left;color:#6b7280;font-weight:600;">
            Description</th>
        </tr>
        {action_rows}
      </table>
    </td>
  </tr>

  <!-- Footer -->
  <tr style="background:#f9fafb;">
    <td style="padding:16px 32px;border-top:1px solid #e5e7eb;">
      <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
        Generated by App Review Pulse · {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
        · Auto-generated — do not reply
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _build_plaintext(pulse: dict, actions_list: list[dict], parsed_llm: dict) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    exec_summary = parsed_llm.get("executive_summary", "")
    top_themes   = parsed_llm.get("top_themes", [])
    user_quotes  = parsed_llm.get("user_quotes", [])
    top_actions  = parsed_llm.get("top_actions", [])

    lines = [
        f"APP REVIEW PULSE — {pulse.get('week_id', '')}",
        "=" * 50,
        "",
        f"Health Score : {pulse.get('health_score')}/100 ({pulse.get('health_label')})",
        f"Avg Rating   : {pulse.get('weighted_avg_rating')}/5.0  ({pulse.get('total_reviews')} reviews)",
        "",
        "EXECUTIVE SUMMARY",
        exec_summary,
        "",
        "TOP 3 THEMES:",
        "\n".join(f"- {t}" for t in top_themes),
        "",
        "TOP 3 ACTIONS:",
        "\n".join(f"- {a}" for a in top_actions),
        "",
        "USER QUOTES:",
        "\n".join(f"\"{q}\"" for q in user_quotes),
        "",
        "DETAILED ACTION ITEMS",
        "-" * 40,
    ]
    for a in actions_list:
        lines.append(
            f"[{a.get('priority')}] {a.get('title')} ({a.get('category')}, {a.get('effort')} effort)"
        )
        lines.append(f"    {a.get('description', '')}")
    lines += ["", f"Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(week_id: str, config: dict[str, Any], logger: logging.Logger) -> None:
    """
    Execute Email Draft & Send.

    Guarantees:
      - Idempotency: skip if send_receipt.json exists.
      - Exactly ONE Groq API call (executive summary).
      - ONE SMTP send per run.
    """
    logger.info("Phase 06 — Email Draft & Send: starting.")
    start = time.monotonic()

    data_root    = Path(config.get("data_root", "data"))
    pulse_path   = data_root / week_id / "04-pulse"   / "pulse.json"
    actions_path = data_root / week_id / "05-actions" / "actions.json"
    themes_path  = data_root / week_id / "03-themes"  / "themes.json"
    output_dir   = data_root / week_id / "06-email"
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / "send_receipt.json"

    # ── Idempotency guard ────────────────────────────────────────────────────
    if receipt_path.exists():
        logger.info(f"  send_receipt.json exists — skipping. ({receipt_path})")
        return

    # ── Load inputs ──────────────────────────────────────────────────────────
    inputs = [(pulse_path, "pulse.json"), (actions_path, "actions.json"), (themes_path, "themes.json")]
    for path, label in inputs:
        if not path.exists():
            raise RuntimeError(f"Phase 06: input not found: {path} ({label})")

    with open(pulse_path,   encoding="utf-8") as f:
        pulse: dict = json.load(f)
    with open(actions_path, encoding="utf-8") as f:
        actions_doc: dict = json.load(f)
    with open(themes_path,  encoding="utf-8") as f:
        themes_doc: dict = json.load(f)

    actions = actions_doc.get("actions", [])
    themes  = themes_doc.get("themes", [])
    logger.info(f"  Loaded pulse (score={pulse.get('health_score')}), {len(actions)} actions, and {len(themes)} themes.")

    # ── Single Groq call — executive summary ─────────────────────────────────
    llm_cfg     = config.get("llm", {})
    model       = llm_cfg.get("model_name", "llama-3.3-70b-versatile")
    api_key_var = llm_cfg.get("api_key_env_var", "GROQ_API_KEY")
    api_key     = os.environ.get(api_key_var)
    if not api_key:
        raise RuntimeError(f"Phase 06: '{api_key_var}' not set.")

    logger.info(f"  Calling Groq (model={model}) for executive summary — ONE call ...")
    raw = _call_groq(
        api_key=api_key, model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_build_summary_prompt(pulse, actions, themes),
    )
    parsed = _parse_response(raw)
    logger.info("  Executive summary generated.")

    # ── Build email ──────────────────────────────────────────────────────────
    html_body  = _build_html(pulse, actions, parsed)
    plain_body = _build_plaintext(pulse, actions, parsed)

    # Save HTML draft
    draft_path = output_dir / "email_draft.html"
    draft_path.write_text(html_body, encoding="utf-8")
    logger.info(f"  HTML draft saved -> {draft_path}")

    # ── Resolve email config ──────────────────────────────────────────────────
    email_cfg = config.get("email", {})
    recipient     = email_cfg.get("recipient", "")
    sender_var    = email_cfg.get("sender_env_var", "EMAIL_SENDER")
    password_var  = email_cfg.get("password_env_var", "EMAIL_APP_PASSWORD")
    smtp_host     = email_cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port     = int(email_cfg.get("smtp_port", 587))
    sender        = os.environ.get(sender_var, "")
    app_password  = os.environ.get(password_var, "")

    if not sender or not app_password or not recipient:
        reason = "SMTP credentials not configured" if not sender else "No recipient specified (draft-only)"
        logger.warning(
            f"  {reason} — saving draft only (not sending)."
        )
        _write_receipt(receipt_path, week_id, recipient, sent=False,
                       reason=reason)
        logger.info("Phase 06 — Email Draft: draft saved (no send). "
                    f"Complete in {time.monotonic()-start:.1f}s.")
        return

    # ── Send via SMTP ────────────────────────────────────────────────────────
    subject = (
        f"[App Review Pulse] {week_id} — "
        f"Health Score {pulse.get('health_score')}/100 ({pulse.get('health_label')})"
    )
    _send_email(
        sender=sender,
        password=app_password,
        recipient=recipient,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        logger=logger,
    )

    _write_receipt(receipt_path, week_id, recipient, sent=True)
    elapsed = time.monotonic() - start
    logger.info(f"Phase 06 — Email Draft & Send: complete in {elapsed:.1f}s.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_groq(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    """Single Groq call — isolated for mocking in tests."""
    from groq import Groq
    client   = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _parse_response(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise RuntimeError(
        f"Phase 06: could not parse LLM response as JSON.\n"
        f"Raw (first 300 chars): {raw[:300]}"
    )


def _send_email(
    sender: str, password: str, recipient: str,
    subject: str, html_body: str, plain_body: str,
    smtp_host: str, smtp_port: int, logger: logging.Logger,
) -> None:
    """Compose and send a multipart/alternative email via STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    logger.info(f"  Sending email to {recipient} via {smtp_host}:{smtp_port} ...")
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
    logger.info(f"  Email sent successfully → {recipient}")


def _write_receipt(
    path: Path, week_id: str, recipient: str,
    sent: bool, reason: str = "",
) -> None:
    receipt = {
        "week_id":   week_id,
        "sent":      sent,
        "recipient": recipient,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    if reason:
        receipt["reason"] = reason
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run Phase 06 — Email Draft & Send standalone.")
    parser.add_argument("--run-label", required=True, help="e.g. historical-12w")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing send_receipt.json and re-send (costs 1 API call + 1 email)")
    parser.add_argument("--draft-only", action="store_true",
                        help="Build and save HTML draft but do not send email")
    args = parser.parse_args()

    import yaml
    config_yaml = _PROJECT_ROOT / "phase-00-orchestration" / "config" / "pipeline_config.yaml"
    with open(config_yaml) as f:
        yaml_cfg = yaml.safe_load(f)

    cfg = {
        "data_root": str(_PROJECT_ROOT / yaml_cfg.get("data_root", "data")),
        "llm":       yaml_cfg.get("llm", {}),
        "email":     yaml_cfg.get("email", {}),
    }

    if args.draft_only:
        # Override recipient so SMTP creds aren't needed
        cfg["email"]["recipient"] = ""

    if args.force:
        cached = Path(cfg["data_root"]) / args.run_label / "06-email" / "send_receipt.json"
        if cached.exists():
            cached.unlink()
            print(f"[--force] Deleted cached receipt {cached}")

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s | %(message)s")
    _logger = _logging.getLogger("phase06.standalone")

    run(week_id=args.run_label, config=cfg, logger=_logger)
