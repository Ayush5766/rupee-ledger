import csv
import io
import json
from datetime import date

import pytest

import app as app_module
from app import create_app

MONTH = "2026-03"


def add(client, **overrides):
    payload = {"description": "Swiggy biryani", "amount": 250.5, "expense_date": f"{MONTH}-05"}
    payload.update(overrides)
    return client.post("/api/expenses", json=payload)


def dash(client, **params):
    return client.get("/api/dashboard", query_string={"month": MONTH, **params})


# ---------------------------------------------------------------- create
def test_create_expense_auto_categorises(client):
    r = add(client)
    assert r.status_code == 201
    e = r.get_json()["expense"]
    assert e["category"] == "Food & Dining"
    assert e["amount"] == 250.5 and e["amount_display"] == "₹250.50"
    assert e["id"] >= 1


def test_create_with_explicit_category_and_string_amount(client):
    e = add(client, category="Health", amount="10").get_json()["expense"]
    assert e["category"] == "Health" and e["amount"] == 10.0


def test_create_defaults_date_to_today(client):
    e = client.post("/api/expenses", json={"description": "Chai", "amount": 20}).get_json()["expense"]
    assert e["expense_date"] == date.today().isoformat()


def test_max_amount_boundary(client):
    ok = add(client, amount=10_000_000)
    assert ok.status_code == 201
    assert ok.get_json()["expense"]["amount_display"] == "₹1,00,00,000.00"
    too_big = add(client, amount=10_000_000.01)
    assert too_big.status_code == 400
    assert "cannot exceed ₹1,00,00,000.00" in too_big.get_json()["error"]


@pytest.mark.parametrize("amount", [0, -5, "abc", None, True, [], {}, "nan", "inf", "1e999999", 0.001, ""])
def test_invalid_amounts_rejected(client, amount):
    r = add(client, amount=amount)
    assert r.status_code == 400
    assert "error" in r.get_json()


@pytest.mark.parametrize("description", [None, "", "   ", 123, "x" * 201, ["a"]])
def test_invalid_descriptions_rejected(client, description):
    r = add(client, description=description)
    assert r.status_code == 400 and "description" in r.get_json()["error"]


def test_description_at_max_length_and_whitespace_cleanup(client):
    assert add(client, description="y" * 200).status_code == 201
    e = add(client, description="  two   spaces\tand\nnewline ").get_json()["expense"]
    assert e["description"] == "two spaces and newline"


@pytest.mark.parametrize("when", ["2026-13-01", "03/05/2026", "2026-02-30", "2026-3-5", "tomorrow", 20260305, "1999-01-01", "2101-01-01"])
def test_invalid_dates_rejected(client, when):
    assert add(client, expense_date=when).status_code == 400


def test_invalid_category_rejected(client):
    r = add(client, category="Crypto")
    assert r.status_code == 400 and "category" in r.get_json()["error"]


def test_invalid_json_bodies(client):
    assert client.post("/api/expenses", data="not json", content_type="application/json").status_code == 400
    assert client.post("/api/expenses", data="{bad", content_type="application/json").status_code == 400
    assert client.post("/api/expenses", json=[1, 2]).status_code == 400
    assert client.post("/api/expenses", data="description=x&amount=1").status_code == 400
    r = client.post("/api/expenses", json={})
    assert r.status_code == 400 and "error" in r.get_json()


def test_oversized_body_returns_json_413(client):
    r = client.post("/api/expenses", data=json.dumps({"description": "x" * 70000, "amount": 1}),
                    content_type="application/json")
    assert r.status_code == 413 and "error" in r.get_json()


def test_special_characters_are_stored_verbatim(client):
    payload = '<img src=x onerror=alert(1)> & "quotes" \' ₹ 日本語'
    e = add(client, description=payload).get_json()["expense"]
    assert e["description"] == payload   # escaping is the renderer's job; the UI uses textContent
    rows = dash(client).get_json()["expenses"]
    assert rows[0]["description"] == payload


# ---------------------------------------------------------------- dashboard
def test_dashboard_empty_database(client):
    d = dash(client).get_json()
    assert d["expenses"] == [] and d["filtered_count"] == 0
    s = d["stats"]
    assert s["total"] == 0 and s["total_display"] == "₹0.00"
    assert s["budget"] == 0 and s["remaining"] is None
    assert s["insights"] and len(s["daily"]) == 31
    assert d["ai_label"] == "AI · Local"


def test_dashboard_totals_and_displays(client):
    add(client, amount=250.5)
    add(client, description="Uber to office", amount=1000, expense_date=f"{MONTH}-07")
    s = dash(client).get_json()["stats"]
    assert s["total"] == 1250.5 and s["total_display"] == "₹1,250.50"
    assert s["count"] == 2
    assert {c["category"] for c in s["category_totals"]} == {"Food & Dining", "Transport"}
    assert s["daily"][4] == 250.5 and s["daily"][6] == 1000


def test_paise_arithmetic_is_exact(client):
    for _ in range(10):
        add(client, amount=0.1)
    assert dash(client).get_json()["stats"]["total"] == 1.0


def test_month_boundaries_and_isolation(client):
    add(client, description="last day", expense_date="2026-03-31")
    add(client, description="first of april", expense_date="2026-04-01")
    add(client, description="end of feb", expense_date="2026-02-28")
    march = [e["description"] for e in dash(client).get_json()["expenses"]]
    assert march == ["last day"]
    april = client.get("/api/dashboard?month=2026-04").get_json()["expenses"]
    assert [e["description"] for e in april] == ["first of april"]


def test_past_and_future_months_work(client):
    for month in ("2020-01", "2099-12"):
        r = client.get("/api/dashboard", query_string={"month": month})
        assert r.status_code == 200 and r.get_json()["stats"]["total"] == 0


def test_dashboard_filters(client):
    add(client, description="Swiggy biryani")
    add(client, description="Uber ride", amount=100)
    add(client, description="100% cotton shirt", amount=999)
    assert [e["description"] for e in dash(client, category="Transport").get_json()["expenses"]] == ["Uber ride"]
    assert [e["description"] for e in dash(client, q="SWIGGY").get_json()["expenses"]] == ["Swiggy biryani"]
    pct = dash(client, q="%").get_json()               # '%' is literal, not a wildcard
    assert [e["description"] for e in pct["expenses"]] == ["100% cotton shirt"]
    both = dash(client, category="Food & Dining", q="uber").get_json()
    assert both["expenses"] == []
    filtered = dash(client, category="Transport").get_json()
    assert filtered["stats"]["count"] == 3             # stats always cover the whole month
    assert filtered["filtered_total_display"] == "₹100.00"


@pytest.mark.parametrize("params", [{"month": "2026-3"}, {"month": "2026-13"}, {"month": "march"},
                                    {"month": "2026-03", "category": "Nope"},
                                    {"month": "2026-03", "q": "x" * 201}])
def test_dashboard_rejects_bad_params(client, params):
    r = client.get("/api/dashboard", query_string=params)
    assert r.status_code == 400 and "error" in r.get_json()


# ---------------------------------------------------------------- update / delete
def test_update_expense(client):
    eid = add(client).get_json()["expense"]["id"]
    r = client.put(f"/api/expenses/{eid}", json={"amount": 300, "category": "Groceries"})
    assert r.status_code == 200
    e = r.get_json()["expense"]
    assert e["amount"] == 300 and e["category"] == "Groceries" and e["description"] == "Swiggy biryani"
    r = client.put(f"/api/expenses/{eid}", json={"description": "Changed", "expense_date": "2026-04-02"})
    assert r.get_json()["expense"]["expense_date"] == "2026-04-02"


def test_update_validation_and_404(client):
    eid = add(client).get_json()["expense"]["id"]
    assert client.put(f"/api/expenses/{eid}", json={}).status_code == 400
    assert client.put(f"/api/expenses/{eid}", json={"amount": -1}).status_code == 400
    assert client.put(f"/api/expenses/{eid}", json={"category": "Nope"}).status_code == 400
    assert client.put(f"/api/expenses/{eid}", json={"expense_date": "bad"}).status_code == 400
    assert client.put("/api/expenses/9999", json={"amount": 5}).status_code == 404
    assert dash(client).get_json()["expenses"][0]["amount"] == 250.5   # unchanged by failed updates


def test_delete_expense(client):
    eid = add(client).get_json()["expense"]["id"]
    r = client.delete(f"/api/expenses/{eid}")
    assert r.status_code == 200 and r.get_json() == {"deleted": eid}
    assert dash(client).get_json()["expenses"] == []
    again = client.delete(f"/api/expenses/{eid}")
    assert again.status_code == 404 and "error" in again.get_json()


# ---------------------------------------------------------------- budget
def test_set_update_and_clear_budget(client):
    add(client, amount=5000)
    r = client.put("/api/budget", json={"month": MONTH, "amount": 30000})
    assert r.status_code == 200 and r.get_json()["budget_display"] == "₹30,000.00"
    s = dash(client).get_json()["stats"]
    assert s["budget"] == 30000 and s["remaining"] == 25000 and s["pct_used"] == 16.7
    client.put("/api/budget", json={"month": MONTH, "amount": 12345678.5})
    assert dash(client).get_json()["stats"]["budget_display"] == "₹1,23,45,678.50"
    client.put("/api/budget", json={"month": MONTH, "amount": 0})
    s = dash(client).get_json()["stats"]
    assert s["budget"] == 0 and s["remaining"] is None and s["remaining_display"] is None


def test_budget_is_per_month(client):
    client.put("/api/budget", json={"month": MONTH, "amount": 1000})
    assert client.get("/api/dashboard?month=2026-04").get_json()["stats"]["budget"] == 0


def test_budget_defaults_to_current_month(client):
    r = client.put("/api/budget", json={"amount": 500})
    assert r.get_json()["month"] == date.today().strftime("%Y-%m")


@pytest.mark.parametrize("body", [{"amount": -1}, {"amount": "abc"}, {"amount": None}, {},
                                  {"amount": 100_000_000.01}, {"month": "2026-3", "amount": 5},
                                  {"month": "2026-00", "amount": 5}])
def test_budget_validation(client, body):
    r = client.put("/api/budget", json=body)
    assert r.status_code == 400 and "error" in r.get_json()


# ---------------------------------------------------------------- categorize / coach / ask
def test_categorize_endpoint(client):
    r = client.post("/api/categorize", json={"description": "BigBasket"})
    assert r.status_code == 200
    assert r.get_json()["category"] == "Groceries" and r.get_json()["source"] == "local"
    assert client.post("/api/categorize", json={"description": "qqq zzz"}).get_json()["category"] == "Other"


@pytest.mark.parametrize("body", [{}, {"description": ""}, {"description": "  "}, {"description": 5}, {"description": "x" * 201}])
def test_categorize_validation(client, body):
    assert client.post("/api/categorize", json=body).status_code == 400


def test_coach_endpoint(client):
    add(client, amount=5000)
    client.put("/api/budget", json={"month": MONTH, "amount": 30000})
    r = client.get("/api/coach", query_string={"month": MONTH})
    d = r.get_json()
    assert r.status_code == 200 and d["source"] == "local"
    assert "₹5,000.00" in d["summary"] and d["tips"] and d["forecast_display"].startswith("₹")
    assert client.get("/api/coach?month=bad").status_code == 400


def test_ask_endpoint(client):
    add(client, amount=250)
    add(client, description="Uber", amount=100)
    r = client.post("/api/ask", json={"question": "How much did I spend on food?", "month": MONTH})
    assert r.status_code == 200
    assert r.get_json()["source"] == "local" and "₹250.00" in r.get_json()["answer"]
    assert "no expenses" in client.post("/api/ask", json={"question": "total?", "month": "2020-01"}).get_json()["answer"].lower()


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": 5},
                                  {"question": "x" * 301}, {"question": "hi", "month": "bad"}])
def test_ask_validation(client, body):
    assert client.post("/api/ask", json=body).status_code == 400


# ---------------------------------------------------------------- CSV export
def test_csv_export(client):
    add(client, description="Swiggy, biryani", amount=250.5)
    add(client, description="=HYPERLINK(\"http://evil\")", amount=1234567.05, expense_date=f"{MONTH}-02")
    add(client, description="outside month", expense_date="2026-04-01")
    r = client.get("/api/export.csv", query_string={"month": MONTH})
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert 'filename="rupee-ledger-2026-03.csv"' in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    assert rows[0] == ["Date", "Description", "Category", "Amount (INR)"]
    assert len(rows) == 3
    assert rows[1][0] == f"{MONTH}-02" and rows[1][3] == "1234567.05"     # plain number, no ₹ or commas
    assert rows[1][1].startswith("'=")                                       # formula injection neutralised
    assert rows[2][1] == "Swiggy, biryani" and rows[2][3] == "250.50"
    assert client.get("/api/export.csv?month=2026-3").status_code == 400


def test_csv_export_empty_month(client):
    rows = list(csv.reader(io.StringIO(client.get("/api/export.csv?month=2020-01").data.decode("utf-8-sig"))))
    assert len(rows) == 1


# ---------------------------------------------------------------- misc
def test_index_and_static_files(client):
    page = client.get("/")
    html = page.data.decode()
    assert page.status_code == 200
    assert "AI · Local" in html and "Rupee Ledger" in html
    assert html.index("chart.umd.min.js") < html.index("js/app.js")   # Chart.js loads first
    assert "Content-Security-Policy" in page.headers
    for path in ("/static/js/app.js", "/static/css/style.css"):
        assert client.get(path).status_code == 200


def test_unknown_api_routes_return_json_errors(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and "error" in r.get_json()
    r = client.patch("/api/budget")
    assert r.status_code == 405 and "error" in r.get_json()
    assert client.get("/api/expenses/abc").status_code == 404


def test_json_keeps_rupee_symbol_unescaped(client):
    assert "₹250.50".encode() in add(client).data


def test_db_path_comes_from_environment(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "ledger.db"
    monkeypatch.setenv("RUPEE_LEDGER_DB", str(target))
    application = create_app()
    assert application.config["DB_PATH"] == str(target) and target.exists()
    application.test_client().post("/api/expenses", json={"description": "Chai", "amount": 10})
    assert target.stat().st_size > 0


def test_data_persists_across_app_instances(tmp_path):
    path = tmp_path / "persist.db"
    add(create_app(path).test_client())
    rows = create_app(path).test_client().get("/api/dashboard", query_string={"month": MONTH}).get_json()["expenses"]
    assert len(rows) == 1


def test_demo_seed_is_realistic_and_idempotent(app):
    with app.app_context():
        added = app_module.seed_demo()
        assert added >= 10
        assert app_module.seed_demo() == 0          # second run does nothing
    d = app.test_client().get("/api/dashboard").get_json()
    assert d["stats"]["count"] == added and d["stats"]["budget"] > 0
    assert len(d["stats"]["category_totals"]) >= 5
    today = date.today().isoformat()
    assert all(e["expense_date"] <= today for e in d["expenses"])   # never seeds the future


def test_theme_switch_and_script_are_served(client):
    html = client.get("/").data.decode()
    assert 'id="theme-toggle"' in html and 'role="switch"' in html
    assert html.index("js/theme.js") < html.index("css/style.css")   # applied before first paint
    assert client.get("/static/js/theme.js").status_code == 200


def test_demo_env_seeds_data_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("RUPEE_LEDGER_DEMO", "1")
    client = create_app(tmp_path / "demo.db").test_client()
    assert client.get("/api/dashboard").get_json()["stats"]["count"] >= 10
    monkeypatch.delenv("RUPEE_LEDGER_DEMO")
    assert create_app(tmp_path / "empty.db").test_client().get("/api/dashboard").get_json()["stats"]["count"] == 0
