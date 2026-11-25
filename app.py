"""Rupee Ledger - Flask app: REST API + single-page UI backed by SQLite.

Run:  python app.py [--demo]
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import random
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv
from flask import (Blueprint, Flask, Response, current_app, g, jsonify,
                   render_template, request)
from werkzeug.exceptions import HTTPException

import ai_engine
from ai_engine import CATEGORIES, inr

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # real environment variables always win

MAX_AMOUNT = Decimal("10000000")      # ₹1 crore per expense
MAX_BUDGET = Decimal("100000000")     # ₹10 crore per month
MAX_DESCRIPTION = 200
MAX_QUESTION = 300
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    description  TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    expense_date TEXT    NOT NULL,           -- YYYY-MM-DD
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (expense_date);
CREATE TABLE IF NOT EXISTS budgets (
    month        TEXT    PRIMARY KEY,        -- YYYY-MM
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0)
);
"""

bp = Blueprint("ledger", __name__)


class ApiError(Exception):
    """Raised by validators; rendered as {"error": message} with a status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def expense_dict(row) -> dict:
    amount = row["amount_paise"] / 100
    return {"id": row["id"], "description": row["description"],
            "category": row["category"], "amount": amount,
            "amount_display": inr(amount), "expense_date": row["expense_date"],
            "created_at": row["created_at"]}


def month_rows(month: str) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM expenses WHERE expense_date BETWEEN ? AND ? "
        "ORDER BY expense_date DESC, id DESC", (f"{month}-01", f"{month}-31")).fetchall()


def month_budget(month: str) -> float:
    row = get_db().execute("SELECT amount_paise FROM budgets WHERE month = ?", (month,)).fetchone()
    return row["amount_paise"] / 100 if row else 0.0


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object (Content-Type: application/json).")
    return data


def parse_amount(value, field="amount", maximum=MAX_AMOUNT, allow_zero=False) -> int:
    """Validate a rupee amount and return it as integer paise."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApiError(f"{field} is required and must be a number.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ApiError(f"{field} must be a number.") from None
    if not number.is_finite():
        raise ApiError(f"{field} must be a finite number.")
    if number < 0 or (number == 0 and not allow_zero):
        raise ApiError(f"{field} must be greater than zero.")
    if number > maximum:
        raise ApiError(f"{field} cannot exceed {inr(maximum)}.")
    number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if number == 0 and not allow_zero:
        raise ApiError(f"{field} must be at least {inr(Decimal('0.01'))}.")
    return int(number * 100)


def clean_text(value, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ApiError(f"{field} is required and must be text.")
    text = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", value)).strip()
    if not text:
        raise ApiError(f"{field} cannot be empty.")
    if len(text) > max_len:
        raise ApiError(f"{field} must be at most {max_len} characters.")
    return text


def parse_month(value) -> str:
    if value is None or value == "":
        return date.today().strftime("%Y-%m")
    if not isinstance(value, str) or not MONTH_RE.match(value):
        raise ApiError("month must be in YYYY-MM format.")
    return value


def parse_date(value) -> str:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ApiError("expense_date must be in YYYY-MM-DD format.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("expense_date is not a valid calendar date.") from None
    if not 2000 <= parsed.year <= 2100:
        raise ApiError("expense_date year must be between 2000 and 2100.")
    return value


def parse_category(value) -> str:
    if value not in CATEGORIES:
        raise ApiError("category must be one of: " + ", ".join(CATEGORIES) + ".")
    return value


def decorate(stats: dict) -> dict:
    """Add pre-formatted ₹ strings (Indian grouping) next to the raw numbers."""
    for key in ("total", "budget", "remaining", "daily_allowance", "avg_per_day", "forecast"):
        stats[f"{key}_display"] = inr(stats[key]) if stats[key] is not None else None
    for item in stats["category_totals"]:
        item["amount_display"] = inr(item["amount"])
    stats["month_label"] = ai_engine.month_label(stats["month"])
    return stats


def ledger_data(month: str):
    rows = [expense_dict(r) for r in month_rows(month)]
    return rows, month_budget(month)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@bp.get("/")
def index():
    return render_template("index.html", categories=CATEGORIES, ai_label=ai_engine.ai_label(),
                           max_amount=int(MAX_AMOUNT), max_budget=int(MAX_BUDGET),
                           max_description=MAX_DESCRIPTION, max_question=MAX_QUESTION,
                           today=date.today().isoformat())


@bp.get("/api/dashboard")
def dashboard():
    month = parse_month(request.args.get("month"))
    category = request.args.get("category", "")
    if category:
        parse_category(category)
    search = request.args.get("q", "").strip()
    if len(search) > MAX_DESCRIPTION:
        raise ApiError(f"q must be at most {MAX_DESCRIPTION} characters.")

    rows, budget = ledger_data(month)
    stats = decorate(ai_engine.build_insights(rows, budget, month))
    shown = [e for e in rows
             if (not category or e["category"] == category)
             and (not search or search.lower() in e["description"].lower())]
    shown_total = round(sum(e["amount"] for e in shown), 2)
    return jsonify({"month": month, "stats": stats, "expenses": shown,
                    "filtered_count": len(shown), "filtered_total": shown_total,
                    "filtered_total_display": inr(shown_total),
                    "ai_label": ai_engine.ai_label()})


@bp.post("/api/expenses")
def create_expense():
    body = json_body()
    description = clean_text(body.get("description"), "description", MAX_DESCRIPTION)
    paise = parse_amount(body.get("amount"))
    when = parse_date(body.get("expense_date") or date.today().isoformat())
    category = body.get("category")
    category = (parse_category(category) if category
                else ai_engine.suggest_category(description)["category"])
    db = get_db()
    cur = db.execute(
        "INSERT INTO expenses (description, category, amount_paise, expense_date, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (description, category, paise, when, datetime.now().isoformat(timespec="seconds")))
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"expense": expense_dict(row)}), 201


@bp.put("/api/expenses/<int:expense_id>")
def update_expense(expense_id: int):
    body = json_body()
    changes = {}
    if "description" in body:
        changes["description"] = clean_text(body["description"], "description", MAX_DESCRIPTION)
    if "amount" in body:
        changes["amount_paise"] = parse_amount(body["amount"])
    if "category" in body:
        changes["category"] = parse_category(body["category"])
    if "expense_date" in body:
        changes["expense_date"] = parse_date(body["expense_date"])
    if not changes:
        raise ApiError("Provide at least one of: description, amount, category, expense_date.")
    db = get_db()
    if not db.execute("SELECT 1 FROM expenses WHERE id = ?", (expense_id,)).fetchone():
        raise ApiError("Expense not found.", 404)
    assignments = ", ".join(f"{col} = ?" for col in changes)  # columns are a fixed whitelist
    db.execute(f"UPDATE expenses SET {assignments} WHERE id = ?", (*changes.values(), expense_id))
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return jsonify({"expense": expense_dict(row)})


@bp.delete("/api/expenses/<int:expense_id>")
def delete_expense(expense_id: int):
    db = get_db()
    cur = db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    if cur.rowcount == 0:
        raise ApiError("Expense not found.", 404)
    return jsonify({"deleted": expense_id})


@bp.put("/api/budget")
def set_budget():
    body = json_body()
    month = parse_month(body.get("month"))
    paise = parse_amount(body.get("amount"), "amount", MAX_BUDGET, allow_zero=True)
    db = get_db()
    if paise == 0:  # a zero budget means "no budget"
        db.execute("DELETE FROM budgets WHERE month = ?", (month,))
    else:
        db.execute("INSERT INTO budgets (month, amount_paise) VALUES (?, ?) "
                   "ON CONFLICT(month) DO UPDATE SET amount_paise = excluded.amount_paise",
                   (month, paise))
    db.commit()
    return jsonify({"month": month, "budget": paise / 100, "budget_display": inr(paise / 100)})


@bp.post("/api/categorize")
def categorize():
    description = clean_text(json_body().get("description"), "description", MAX_DESCRIPTION)
    return jsonify(ai_engine.suggest_category(description))


@bp.get("/api/coach")
def coach():
    month = parse_month(request.args.get("month"))
    rows, budget = ledger_data(month)
    return jsonify(decorate(ai_engine.coach(rows, budget, month)))


@bp.post("/api/ask")
def ask():
    body = json_body()
    question = clean_text(body.get("question"), "question", MAX_QUESTION)
    month = parse_month(body.get("month"))
    rows, budget = ledger_data(month)
    return jsonify(ai_engine.ask_assistant(question, rows, budget, month))


def _csv_safe(text: str) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start)."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@bp.get("/api/export.csv")
def export_csv():
    month = parse_month(request.args.get("month"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Description", "Category", "Amount (INR)"])
    for row in reversed(month_rows(month)):  # oldest first
        paise = row["amount_paise"]
        writer.writerow([row["expense_date"], _csv_safe(row["description"]),
                         row["category"], f"{paise // 100}.{paise % 100:02d}"])
    # BOM so Excel opens UTF-8 correctly
    return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="rupee-ledger-{month}.csv"'})


# --------------------------------------------------------------------------
# Demo data
# --------------------------------------------------------------------------

# (descriptions, category, min ₹, max ₹, entries per full month, once-a-month?)
DEMO_TEMPLATES = [
    (["House rent - 2BHK"], "Rent & Housing", 18000, 18000, 1, True),
    (["Electricity bill BESCOM"], "Bills & Utilities", 1400, 2200, 1, True),
    (["Jio recharge", "Airtel broadband"], "Bills & Utilities", 499, 999, 1, True),
    (["Netflix subscription"], "Entertainment", 649, 649, 1, True),
    (["Swiggy biryani", "Zomato dinner", "Starbucks coffee", "Chai and samosa", "Dominos pizza"],
     "Food & Dining", 120, 850, 14, False),
    (["BigBasket order", "Blinkit groceries", "DMart monthly stock", "Fruits and vegetables"],
     "Groceries", 250, 3200, 7, False),
    (["Uber to office", "Rapido bike taxi", "Metro card recharge", "Petrol", "IRCTC ticket"],
     "Transport", 60, 1500, 10, False),
    (["Amazon order", "Myntra shirt", "Flipkart headphones"], "Shopping", 399, 3499, 3, False),
    (["Apollo pharmacy"], "Health", 180, 950, 2, False),
    (["BookMyShow movie", "Spotify premium"], "Entertainment", 119, 750, 2, False),
    (["Udemy Python course"], "Education", 449, 649, 1, False),
]


def seed_demo(budget_rupees: int = 65000) -> int:
    """Insert realistic sample data for the current month; returns rows added.

    Does nothing if the current month already has expenses.
    """
    today = date.today()
    month = today.strftime("%Y-%m")
    days_in_month = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - date(today.year, today.month, 1)).days
    db = get_db()
    if month_rows(month):
        return 0
    rng = random.Random(month)  # same sample data every time for a given month
    added = 0
    for descriptions, category, low, high, per_month, monthly in DEMO_TEMPLATES:
        count = 1 if monthly else max(1, round(per_month * today.day / days_in_month))
        for _ in range(count):
            day = 1 if descriptions[0].startswith("House rent") else rng.randint(1, today.day)
            paise = rng.randrange(low * 100, high * 100 + 1, 50)
            db.execute("INSERT INTO expenses (description, category, amount_paise, expense_date, created_at) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (rng.choice(descriptions), category, paise, f"{month}-{day:02d}",
                        datetime.now().isoformat(timespec="seconds")))
            added += 1
    db.execute("INSERT OR REPLACE INTO budgets (month, amount_paise) VALUES (?, ?)",
               (month, budget_rupees * 100))
    db.commit()
    return added


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------

def create_app(db_path: str | os.PathLike | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or os.environ.get("RUPEE_LEDGER_DB") or BASE_DIR / "rupee_ledger.db")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.json.ensure_ascii = False   # keep ₹ readable in raw JSON
    app.json.sort_keys = False
    init_db(app.config["DB_PATH"])
    app.register_blueprint(bp)
    # Free hosts wipe the disk on restart; this re-seeds sample data so a public demo is never empty.
    if os.environ.get("RUPEE_LEDGER_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}:
        with app.app_context():
            seed_demo()

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify({"error": err.message}), err.status

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if request.path.startswith("/api/"):
            message = "Request body too large." if err.code == 413 else err.description
            return jsonify({"error": message}), err.code
        return err

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        app.logger.exception("Unhandled error: %s", err)
        return jsonify({"error": "Internal server error."}), 500

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Rupee Ledger - smart expense tracker")
    parser.add_argument("--demo", action="store_true", help="seed sample data for the current month")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    args = parser.parse_args()

    app = create_app()
    if args.demo:
        with app.app_context():
            added = seed_demo()
        print(f"Demo data: added {added} expenses." if added
              else "Demo data skipped: this month already has expenses.")
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    print(f"Rupee Ledger running at http://{args.host}:{args.port}  ({ai_engine.ai_label()})")
    app.run(host=args.host, port=args.port, debug=debug)


if __name__ == "__main__":
    main()
