import pytest

import ai_engine
from ai_engine import CATEGORIES, KEYWORDS, classify_local, suggest_category


@pytest.mark.parametrize("text, expected", [
    ("Swiggy biryani", "Food & Dining"),
    ("BigBasket", "Groceries"),
    ("IRCTC ticket", "Transport"),
    ("Netflix subscription", "Entertainment"),
    ("Apollo pharmacy", "Health"),
    ("Swiggy Instamart order", "Groceries"),   # longer, more specific match wins the tie
    ("big basket weekly", "Groceries"),        # multi-word keyword
    ("Veggies and snacks", "Groceries"),       # plural/singular handling
    ("xyzzy qwerty", "Other"),
    ("", "Other"),
    ("   ", "Other"),
    ("!!!", "Other"),
])
def test_keyword_classifier(text, expected):
    assert classify_local(text)[0] == expected


def test_keywords_match_whole_words_only():
    # "ola", "pub" and "tea" are keywords, but must not match inside longer words.
    assert classify_local("cola")[0] == "Other"
    assert classify_local("republic")[0] == "Other"
    assert classify_local("steak")[0] == "Other"
    assert classify_local("tea")[0] == "Food & Dining"


def test_confidence_is_bounded_and_zero_for_unknown():
    assert classify_local("unknown thing")[1] == 0.0
    assert 0 < classify_local("Swiggy biryani")[1] <= 0.97


def test_no_duplicate_keywords_and_all_categories_valid():
    flat = [word for words in KEYWORDS.values() for word in words]
    assert len(flat) == len(set(flat)), "a keyword appears more than once"
    assert all(word == word.lower() for word in flat)
    assert set(KEYWORDS) <= set(CATEGORIES)
    assert flat.count("pharmacy") == 1


def test_duplicate_keywords_are_rejected_at_build_time(monkeypatch):
    monkeypatch.setitem(ai_engine.KEYWORDS, "Health", ai_engine.KEYWORDS["Health"] + ["swiggy"])
    with pytest.raises(ValueError):
        ai_engine._build_index()


def test_suggest_category_is_local_without_api_key():
    result = suggest_category("Swiggy biryani")
    assert result["category"] == "Food & Dining"
    assert result["source"] == "local"
    assert suggest_category("zzzz")["category"] == "Other"
