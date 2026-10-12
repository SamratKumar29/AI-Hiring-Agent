import pytest

from brain import salary as s

CASES = [
    ("$120k-150k", None, (120_000, 150_000, "USD")),
    ("$120 - 150k", None, (120_000, 150_000, "USD")),
    ("₹20L – ₹30L • No equity", None, (2_000_000, 3_000_000, "INR")),
    ("25 LPA", None, (2_500_000, 2_500_000, "INR")),
    ("20-30 LPA", None, (2_000_000, 3_000_000, "INR")),
    ("₹20,000 – ₹30,000 • No equity", None, (240_000, 360_000, "INR")),        # monthly (intern) heuristic
    ("£45/hr", None, (93_600, 93_600, "GBP")),
    ("€4,000 per month", None, (48_000, 48_000, "EUR")),
    ("USD 90,000 - 110,000 a year", None, (90_000, 110_000, "USD")),
    ("S$8k-10k monthly", None, (96_000, 120_000, "SGD")),
    ("1.5 Cr", None, (15_000_000, 15_000_000, "INR")),
    ("120000", "USD", (120_000, 120_000, "USD")),
]


@pytest.mark.parametrize("text,default,want", CASES)
def test_parse_range(text, default, want):
    r = s.parse_range(text, default)
    assert (r["min"], r["max"], r["currency"]) == want, r


@pytest.mark.parametrize("text", [None, "", "Competitive", "negotiable", "5 years experience", "0"])
def test_not_stated(text):
    assert s.parse_range(text) is None


def test_convert_and_annual_min():
    assert s.annual_min("$100k", "INR") == int(100_000 * 1.0 / 0.012)
    assert s.annual_min("25 LPA", "INR") == 2_500_000
    assert s.annual_min("Competitive", "INR") is None
    assert s.convert(5, "XXX", "INR") == 5                       # unknown currency: untouched
