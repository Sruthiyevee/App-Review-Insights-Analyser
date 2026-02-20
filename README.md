# 📊 App Review Pulse

> An automated weekly pipeline that scrapes Ind Money app reviews, extracts themes with an LLM, computes a Product Health Score, generates PM action items, and emails a polished weekly report — all with exactly **4 Groq API calls per run**.

---

## ✨ What it does

Every Monday, the pipeline:

1. **Scrapes** reviews from the Apple App Store + Google Play Store
2. **Cleans** and deduplicates them (1,387 reviews across 12 weeks)
3. **Extracts** up to 10 recurring themes using Groq's LLM
4. **Computes** a 0–100 Product Health Score (no LLM — pure math)
5. **Synthesises** a narrative pulse with strengths, pain points & watch list
6. **Generates** 5–8 prioritised PM action items (P1 / P2 / P3)
7. **Sends** a rich HTML email to the product team

---

## 🏗️ Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full Mermaid diagram and tech stack breakdown.

**Quick view:**
```
Phase 00  →  Phase 01  →  Phase 02  →  Phase 03  →  Phase 04  →  Phase 05  →  Phase 06
Orchestrator  Ingestion   Cleaning    Themes(LLM) Pulse(LLM)  Actions(LLM) Email(LLM+SMTP)
```

---

## 🗂️ Project Structure

```
App-Review-Insights-Analyser/
├── phase-00-orchestration/       # Config + pipeline dispatcher
│   └── config/pipeline_config.yaml
├── phase-01-ingestion/           # iOS + Android scrapers
├── phase-02-cleaning/            # Dedup, normalise, CSV/JSON export
├── phase-03-theme-extraction/    # LLM theme extraction + tests
├── phase-04-pulse-synthesis/     # Health score + LLM narrative + tests
├── phase-05-action-items/        # LLM PM action items + tests
├── phase-06-email-draft/         # LLM exec summary + SMTP send + tests
├── data/                         # All pipeline outputs (gitignored)
│   └── {run-label}/
│       ├── 01-raw/   reviews_raw.json
│       ├── 02-clean/ reviews_clean.json / .csv
│       ├── 03-themes/themes.json
│       ├── 04-pulse/ pulse.json
│       ├── 05-actions/actions.json
│       └── 06-email/ email_draft.html / send_receipt.json
├── .env                          # API keys (never commit)
├── requirements.txt
├── README.md
└── ARCHITECTURE.md
```

---

## ⚙️ Setup

### 1. Clone & install

```bash
git clone <repo-url>
cd App-Review-Insights-Analyser
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env   # or edit .env directly
```

Fill in:

```env
GROQ_API_KEY=gsk_...              # https://console.groq.com/keys
EMAIL_SENDER=you@gmail.com         # Gmail sender address
EMAIL_APP_PASSWORD=abcdefghijklmnop  # Gmail App Password (16 chars)
```

> **Gmail App Password:** Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Requires 2-Step Verification to be ON.

### 3. Configure `pipeline_config.yaml`

Edit `phase-00-orchestration/config/pipeline_config.yaml`:

```yaml
apps:
  ios:     { app_id: "1547840544", name: "Ind Money" }
  android: { package_name: "com.indwealth.indmoney", name: "Ind Money" }

email:
  recipient: "team@yourcompany.com"
```

---

## 🚀 Running the Pipeline

### Full pipeline (all phases)

```bash
python phase-00-orchestration/phase_dispatcher.py --run-label 2026-W08
```

### Individual phases

```bash
# Phase 01 — scrape last 12 weeks of reviews
python phase-01-ingestion/ingestor.py --lookback 12

# Phase 02 — clean
python phase-02-cleaning/cleaner.py --run-label historical-12w

# Phase 03 — theme extraction (1 Groq call)
python phase-03-theme-extraction/theme_extractor.py --run-label historical-12w

# Phase 04 — pulse synthesis (1 Groq call)
python phase-04-pulse-synthesis/pulse_synthesizer.py --run-label historical-12w

# Phase 05 — action items (1 Groq call)
python phase-05-action-items/action_generator.py --run-label historical-12w

# Phase 06 — email send (1 Groq call + SMTP)
python phase-06-email-draft/email_drafter.py --run-label historical-12w
```

### Force re-run (override idempotency)

```bash
python phase-06-email-draft/email_drafter.py --run-label historical-12w --force
```

### Draft email only (no SMTP)

```bash
python phase-06-email-draft/email_drafter.py --run-label historical-12w --draft-only
```

---

## 🧪 Running Tests

```bash
# All 52 tests
python -m pytest phase-03-theme-extraction/tests/ \
                  phase-04-pulse-synthesis/tests/ \
                  phase-05-action-items/tests/ \
                  phase-06-email-draft/tests/ -v

# Single phase
python -m pytest phase-04-pulse-synthesis/tests/ -v
```

All tests are **fully offline** — Groq API and SMTP are mocked with `unittest.mock`.

| Phase | Tests | Coverage |
|---|---|---|
| Phase 03 — Theme Extraction | 13 | Sampling, parsing, idempotency, errors |
| Phase 04 — Pulse Synthesis | 15 | Score boundaries, labels, idempotency, errors |
| Phase 05 — Action Items | 11 | Happy path, P1 schema, missing inputs, errors |
| Phase 06 — Email Draft | 13 | SMTP mock, draft-only, HTML content, errors |
| **Total** | **52** | **All pass** |

---

## 📤 Sample Output

**Product Health Pulse — historical-12w**

| Metric | Value |
|---|---|
| Health Score | **74 / 100 — Stable** |
| Avg Rating | 3.7 / 5.0 |
| Reviews Analysed | 133 (sampled from 1,387) |

**Top Themes:**

| Sentiment | Theme |
|---|---|
| ✅ Positive | Good Experience · Investment Features · User Education |
| ❌ Negative | Customer Support Issues · Technical Issues · Withdrawal Issues |
| 👀 Watch List | App Interface · Security Concerns |

**P1 Action Items:** Improve Customer Support · Resolve Technical Issues · Address Withdrawal Issues

---

## 🔑 Key Design Decisions

| Decision | Why |
|---|---|
| **1 Groq call per LLM phase** | Controls cost, ensures predictable runtime |
| **Idempotency guard** | Re-running the pipeline never double-charges the API |
| **File-based state handoff** | Each phase is independently re-runnable with no shared state |
| **Health score without LLM** | Deterministic, reproducible, fast — LLM only writes prose |
| **Stratified sampling (Phase 03)** | Prevents skewed analysis from dominant rating groups |

---

## 📦 Dependencies

```
requests              # iOS Apple RSS API
google-play-scraper   # Android reviews
groq                  # LLM API (Phases 03–06)
PyYAML                # pipeline_config.yaml
python-dotenv         # .env loader
pytest                # Test runner
```

Install: `pip install -r requirements.txt`

---

## 🔐 Security Notes

- **Never commit `.env`** — it contains your Groq API key and Gmail App Password
- `.gitignore` already excludes `.env` and `data/`
- Gmail App Passwords are scoped and can be revoked individually at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)

---

## 🗺️ Roadmap

- [ ] Slack integration — push pulse to `#product-updates`
- [ ] Jira integration — auto-create tickets from P1 actions
- [ ] Streamlit dashboard — browse historical pulses + trend charts
- [ ] Notion sync — archive weekly pulses
- [ ] Competitor analysis — parallel pipeline for competitor app reviews
