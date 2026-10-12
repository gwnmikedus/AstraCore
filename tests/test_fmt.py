import pytest

from astracore.core.fmt import pct


@pytest.mark.parametrize("value, expected", [
    (0, "0%"), (0.1, "<1%"), (0.9, "<1%"), (1, "1%"), (10, "10%"),
    (20, "20%"), (100, "100%"), (1000, "1000%"), (-10, "-10%"), (-0.1, "0%"),
])
def test_whole_percentages(value, expected):
    assert pct(value, 0) == expected


@pytest.mark.parametrize("value, digits, expected", [
    (10, 1, "10%"), (0.1, 1, "0.1%"), (10.25, 2, "10.25%"), (10.2, 2, "10.2%"),
    (None, 0, "–"), ("", 0, "–"), (float("nan"), 0, "–"),
])
def test_decimal_and_missing_percentages(value, digits, expected):
    assert pct(value, digits) == expected
