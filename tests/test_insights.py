from datetime import date

import ai_engine
from ai_engine import ask_assistant, build_insights, find_category

MONTH = "2026-03"
TODAY = date(2026, 3, 10)


def exp(day, amount, category="Food & Dining", description="Lunch", month=MONTH):
    return {"amount": amount, "category": category, "description": description,
            "expense_date": f"{month}-{day:02d}"}


def levels(stats):
    return {i["level"] for i in stats["insights"]}


def test_no_expenses():
    s = build_insights([], 0, MONTH, TODAY)
    assert s["total"] == 0 and s["count"] == 0
    assert s["forecast"] == 0 and s["daily_allowance"] is None
    assert s["top_category"] is None
    assert s["insights"][0]["level"] == "info"
    assert "No expenses" in s["insights"][0]["text"]
    assert len(s["daily"]) == 31


def test_under_budget():
    rows = [exp(2, 1500), exp(5, 2000, "Transport"), exp(9, 1500, "Groceries")]
    s = build_insights(rows, 30000, MONTH, TODAY)
    assert s["total"] == 5000
    assert s["remaining"] == 25000
    assert s["pct_used"] == 16.7
    assert s["days_left"] == 22                      # today (10th) through 31st
    assert s["daily_allowance"] == round(25000 / 22, 2)
    assert "good" in levels(s) and "bad" not in levels(s)
    assert round(sum(c["amount"] for c in s["category_totals"]), 2) == s["total"]


def test_over_budget():
    rows = [exp(1, 20000, "Rent & Housing"), exp(4, 15000, "Shopping")]
    s = build_insights(rows, 30000, MONTH, TODAY)
    assert s["remaining"] == -5000
    assert s["daily_allowance"] == 0
    assert "bad" in levels(s)
    assert any("over budget by ₹5,000.00" in i["text"] for i in s["insights"])


def test_near_budget_warns():
    s = build_insights([exp(3, 8500)], 10000, MONTH, TODAY)
    assert "warn" in levels(s)


def test_rising_spend_warning():
    today = date(2026, 3, 20)
    rows = [exp(d, 100) for d in range(7, 14)] + [exp(d, 300) for d in range(14, 21)]
    s = build_insights(rows, 100000, MONTH, today)
    assert any(i["level"] == "warn" and "rising" in i["text"].lower() for i in s["insights"])


def test_flat_spend_has_no_rising_warning():
    today = date(2026, 3, 20)
    rows = [exp(d, 200) for d in range(1, 21)]
    s = build_insights(rows, 100000, MONTH, today)
    assert not any("rising" in i["text"].lower() for i in s["insights"])


def test_forecast_and_pace_warning():
    rows = [exp(d, 1000) for d in range(1, 11)]       # ₹1,000/day for 10 days
    s = build_insights(rows, 20000, MONTH, TODAY)
    assert s["avg_per_day"] == 1000
    assert s["forecast"] == 31000
    assert any("current pace" in i["text"] for i in s["insights"])


def test_past_and_future_months():
    past = build_insights([exp(5, 700)], 1000, MONTH, date(2026, 5, 10))
    assert past["period"] == "past" and past["forecast"] == 700
    assert past["days_left"] == 0 and past["daily_allowance"] is None
    future = build_insights([], 5000, "2099-01", TODAY)
    assert future["period"] == "future" and future["days_elapsed"] == 0
    assert future["daily_allowance"] == round(5000 / 31, 2)


def test_leap_year_february_has_29_days():
    assert len(build_insights([], 0, "2028-02", TODAY)["daily"]) == 29
    assert len(build_insights([], 0, "2027-02", TODAY)["daily"]) == 28


def test_ask_matches_category_names_on_word_boundaries():
    assert find_category("what did I spend on another thing") is None   # "another" != "other"
    assert find_category("show me other expenses") == "Other"
    assert find_category("how much on food?") == "Food & Dining"
    assert find_category("grocery spend") == "Groceries"
    assert find_category("breakfast") is None


def test_local_assistant_answers():
    rows = [exp(2, 500, "Food & Dining", "Swiggy"), exp(3, 1500, "Transport", "Uber"),
            exp(4, 250, "Food & Dining", "Zomato")]
    ask = lambda q: ask_assistant(q, rows, 10000, MONTH, TODAY)
    assert "₹750.00" in ask("How much did I spend on food?")["answer"]
    assert "Uber" in ask("What is my biggest expense?")["answer"]
    assert "₹7,750.00" in ask("How much is left in my budget?")["answer"]
    assert "Transport" in ask("Which category do I spend the most on?")["answer"]
    assert "₹500.00" in ask("how much did I spend on swiggy")["answer"]
    assert ask("anything")["source"] == "local"
    assert "no expenses" in ask_assistant("hi", [], 0, MONTH, TODAY)["answer"].lower()


def test_another_does_not_trigger_other_category():
    rows = [exp(2, 500, "Other", "Misc stuff"), exp(3, 100, "Food & Dining", "Tea")]
    answer = ask_assistant("how much did I spend on another day", rows, 0, MONTH, TODAY)["answer"]
    assert "on Other" not in answer
