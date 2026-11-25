import pytest

from ai_engine import inr


@pytest.mark.parametrize("value, expected", [
    (0, "₹0.00"),
    (999, "₹999.00"),
    (1000, "₹1,000.00"),
    (100000, "₹1,00,000.00"),
    (1234567, "₹12,34,567.00"),
    (12345678.5, "₹1,23,45,678.50"),
    (-1234.5, "-₹1,234.50"),
    (-12345678, "-₹1,23,45,678.00"),
    (0.005, "₹0.01"),       # rounds half up
    (-0.001, "₹0.00"),      # no "-₹0.00"
    ("1500", "₹1,500.00"),  # numeric strings are accepted
])
def test_inr_formats_with_lakh_crore_grouping(value, expected):
    assert inr(value) == expected


@pytest.mark.parametrize("bad", ["abc", None, float("nan"), float("inf")])
def test_inr_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        inr(bad)
