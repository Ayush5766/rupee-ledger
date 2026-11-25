# Rupee Ledger

A smart expense tracker for Indian households. Log spending in ₹, set a monthly budget, get an AI coach, a month-end forecast and plain-English answers about your money. It works fully offline with a local keyword model, and optionally upgrades to an LLM when an OpenAI key is present.

![Screenshot placeholder](docs/screenshot.png)
<!-- Replace docs/screenshot.png with a screenshot of the running app. -->

## Features

- Add, edit, delete, filter (category) and search expenses; export any month to CSV
- All money in ₹ with lakh/crore grouping (₹12,34,567.00) in the UI, API and chart axes
- Monthly budget with a progress bar and a per-day allowance
- AI auto-categorisation while you type (local keyword model; LLM for unknown descriptions)
- AI Coach: summary, month-end forecast, rising/cooling spend detection, tips
- "Ask your money": natural-language questions with a local fallback
- Category doughnut and daily-spend bar charts (Chart.js)
- Light/dark theme switch (saved in your browser; dark by default), including theme-aware charts
- Animated saffron-and-midnight design: drifting colour glows, jaali lattice, counter-rotating mandalas, floating ₹ coins and sparks, staggered card entrances, shimmering headings, count-up numbers; all motion is disabled under `prefers-reduced-motion`
- Accessible: labelled inputs, `aria-live` regions, visible focus, skip link
- Safe: server-side validation, parameterised SQL, no `innerHTML` for user text, CSP header, CSV formula-injection guard

## Tech stack

Python 3.10+, Flask, SQLite (`sqlite3`), vanilla JavaScript, Chart.js (CDN), optional OpenAI REST API via `requests`, pytest.

## Architecture

```
 Browser (index.html + app.js + Chart.js)
      │  fetch JSON
      ▼
 Flask (app.py) ── validation ──► SQLite (expenses, budgets; amounts stored as integer paise)
      │
      ▼
 ai_engine.py
   ├─ inr()                 Indian currency formatting
   ├─ classify_local()      whole-word keyword model
   ├─ build_insights()      totals, pace, forecast, tips
   ├─ ask_assistant()       local Q&A
   └─ _chat()  ──(optional, key set)──► OpenAI; any failure → silent local fallback
```

## Setup

Requires Python 3.10+.

**macOS / Linux**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py --demo      # --demo seeds sample data for the current month
```

**Windows (PowerShell)**
```powershell
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py --demo
```

Open http://127.0.0.1:5000. The header pill shows **AI · Local** when no API key is set.

Charts load Chart.js from jsDelivr. If you are fully offline, download `chart.umd.min.js` into `static/vendor/` and point the `<script>` tag in `templates/index.html` at it. Without it everything else still works and a notice replaces the charts.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Enable OpenAI mode (optional)

```bash
cp .env.example .env      # then set OPENAI_API_KEY=sk-...
python app.py
```
The pill changes to **AI · OpenAI**. If a request fails or times out, the app falls back to local logic without errors.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Enables LLM features | unset (local mode) |
| `OPENAI_MODEL` | Model name | `gpt-4o-mini` |
| `RUPEE_LEDGER_DB` | SQLite file path | `rupee_ledger.db` |
| `FLASK_DEBUG` | `1` enables debug mode | off |
| `RUPEE_LEDGER_DEMO` | `1` seeds sample data at startup | off |
| `HOST`, `PORT` | Server bind | `127.0.0.1`, `5000` |

## Deployment

```bash
pip install -r requirements.txt
gunicorn "app:create_app()"
```
A `Procfile` is included for Heroku-style platforms. Put `RUPEE_LEDGER_DB` on a persistent disk.

**Render (free tier):** Build command `pip install -r requirements.txt`, start command `gunicorn "app:create_app()"`. The free tier's disk is temporary, so set `RUPEE_LEDGER_DEMO=1` to re-seed sample data on every start. All visitors share one ledger because there are no user accounts.

## API reference

Errors are JSON: `{"error": "message"}` with status 400 (validation), 404, 405, 413 or 500.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/dashboard?month=YYYY-MM&category=&q=` | Stats, insights, charts data and (filtered) expenses |
| POST | `/api/expenses` | Create `{description, amount, expense_date?, category?}` → 201 |
| PUT | `/api/expenses/<id>` | Update any of description, amount, category, expense_date |
| DELETE | `/api/expenses/<id>` | Delete an expense |
| PUT | `/api/budget` | `{month?, amount}`; amount 0 removes the budget |
| POST | `/api/categorize` | `{description}` → category, confidence, source |
| GET | `/api/coach?month=YYYY-MM` | Summary, forecast, insights, tips |
| POST | `/api/ask` | `{question, month?}` → answer, source |
| GET | `/api/export.csv?month=YYYY-MM` | CSV with plain-number amounts |

Limits: amount ≤ ₹1 crore per expense, budget ≤ ₹10 crore, description ≤ 200 characters, question ≤ 300.

## Resume bullets

- Built a full-stack expense tracker (Flask, SQLite, vanilla JS, Chart.js) with 9 REST endpoints, integer-paise storage for exact money arithmetic and lakh/crore currency formatting.
- Implemented an offline-first AI layer: a whole-word keyword classifier, rule-based coach with forecast and spending-trend detection, and natural-language Q&A, with an optional OpenAI upgrade that falls back silently on any failure.
- Wrote 141 automated pytest cases covering validation, edge cases, month boundaries, LLM-outage fallback and CSV export, alongside XSS-safe rendering, CSP headers and CSV formula-injection protection.
- Designed an accessible, responsive UI (375px to 1440px) with ARIA live regions, keyboard focus states and reduced-motion support.

## Future improvements

- User accounts and multi-device sync; recurring expenses
- Per-category budgets and alerts
- Receipt scanning (OCR) and bank-SMS import
- Vendor Chart.js locally with a service worker for a fully offline PWA
- Timezone setting (the server's local date is used today)
