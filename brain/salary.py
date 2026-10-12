"""Parse salary text ("$120k-150k", "₹20L – ₹30L", "25 LPA", "£45/hr") into annual numbers.

Approximations (documented on purpose - edit RATES_TO_USD when currencies move):
* RATES_TO_USD are fixed rough rates, good enough for a "is it clearly below my minimum?" filter.
* INR amounts without a unit (L/lakh/LPA/Cr/k) below 300,000 are read as MONTHLY (typical for internships).
"""
import re

RATES_TO_USD = {"USD": 1.0, "INR": 0.012, "EUR": 1.08, "GBP": 1.27, "SGD": 0.74, "AUD": 0.65, "CAD": 0.73,
                "AED": 0.272, "CHF": 1.1, "JPY": 0.0065}
SYMBOLS = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|l|lac|lacs|lakh|lakhs|lpa|cr|crore|crores)?\b", re.I)
MULT = {"k": 1e3, "m": 1e6, "mn": 1e6, "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5, "lpa": 1e5,
        "cr": 1e7, "crore": 1e7, "crores": 1e7}


def _currency(text: str, default: str | None) -> str | None:
    m = re.search(r"\b(S|A|C)\$", text)                                  # S$ / A$ / C$ before the bare $
    if m:
        return {"S": "SGD", "A": "AUD", "C": "CAD"}[m.group(1)]
    for sym, cur in SYMBOLS.items():
        if sym in text:
            return cur
    m = re.search(r"\b(USD|INR|EUR|GBP|SGD|AUD|CAD|AED|CHF|JPY)\b", text, re.I)
    if m:
        return m.group(1).upper()
    if re.search(r"\bRs\.?|\blpa\b|\blakh|\blacs?\b|\bcrores?\b|\d\s*cr\b", text, re.I):
        return "INR"
    return default


def parse_range(text: str | None, default_currency: str | None = None) -> dict | None:
    """-> {"min", "max", "currency", "period"} with ANNUAL min/max in the text's own currency, or None."""
    if not text or not re.search(r"\d", text):
        return None
    t = str(text).replace("\u2013", "-").replace("\u2014", "-").replace(" to ", "-")
    t = re.split(r"[•|·]", t)[0]                                         # drop "• No equity" style tails
    cur = _currency(t, default_currency)
    nums = [(float(m.group(1).replace(",", "")), (m.group(2) or "").lower()) for m in NUM_RE.finditer(t)]
    nums = [n for n in nums if n[0] > 0][:2]
    if not nums:
        return None
    if len(nums) == 2 and not nums[0][1] and nums[1][1] and nums[0][0] < nums[1][0] * 1.0:
        nums[0] = (nums[0][0], nums[1][1])                                # "20-30L" / "120-150k"
    vals = [v * MULT.get(u, 1) for v, u in nums]
    period = "year"
    if re.search(r"/\s*h(ou)?r|per hour|hourly|\bph\b", t, re.I):
        period, vals = "hour", [v * 2080 for v in vals]
    elif re.search(r"/\s*mo(nth)?|per month|monthly|\bpm\b", t, re.I):
        period, vals = "month", [v * 12 for v in vals]
    elif cur == "INR" and not any(u for _, u in nums) and vals[0] < 300_000:
        period, vals = "month", [v * 12 for v in vals]
    elif not any(u for _, u in nums) and vals[0] < 1000 and cur != "INR":
        return None                                                       # "5 years" / stray numbers
    lo, hi = min(vals), max(vals)
    return {"min": int(lo), "max": int(hi), "currency": cur, "period": period}


def convert(amount: float, src: str | None, dst: str | None) -> float:
    """Convert between currencies using the rough RATES_TO_USD. Unknown currency -> unchanged."""
    if not src or not dst or src == dst or src not in RATES_TO_USD or dst not in RATES_TO_USD:
        return amount
    return amount * RATES_TO_USD[src] / RATES_TO_USD[dst]


def annual_min(text: str | None, target_currency: str | None = None, default_currency: str | None = None) -> int | None:
    """Lowest stated annual salary in `target_currency` (or the text's own), None when not stated."""
    r = parse_range(text, default_currency)
    if not r:
        return None
    return int(convert(r["min"], r["currency"], target_currency))
