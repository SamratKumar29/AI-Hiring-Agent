"""Wellfound role/location listing pages (server-rendered job cards: title, company, salary)."""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from brain import salary
from brain.scrapers import _http

DEFAULT_URL = "https://wellfound.com/role/l/software-engineer/india"
SALARY_RE = re.compile(r"[₹$€£]\s?[\d.,]+\s?[kKLlMm]?\s*[–-]\s*[₹$€£]?\s?[\d.,]+\s?[kKLlMm]?")


def parse(html: str, base: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], set()
    for a in soup.select('a[href^="/jobs/"]'):
        if not re.match(r"/jobs/\d+-", a["href"]) or a["href"] in seen:
            continue
        seen.add(a["href"])
        card, comp = a, None
        for _ in range(8):                                    # climb until the card also contains the company link
            card = card.parent
            if card is None:
                break
            comp = card.select_one('a[href^="/company/"] h2') or None
            if comp:
                break
        if card is None:
            continue
        text = card.get_text(" ", strip=True)
        # the company header precedes ALL of its jobs; the job row text is only what follows the job link
        row = a.find_parent("div", class_=re.compile("mb-1|w-full")) or a.parent
        sal = SALARY_RE.search(row.parent.get_text(" ", strip=True) if row and row.parent else text)
        st = sal.group(0).strip() if sal else ""
        loc = re.search(r"\b(Remote|[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*)\b\s*(?:•|·)", row.parent.get_text(" ", strip=True)) if row and row.parent else None
        rows.append({"url": urljoin("https://wellfound.com", a["href"]), "title": a.get_text(strip=True),
                     "company": comp.get_text(strip=True) if comp else None, "location": loc.group(1) if loc else None,
                     "description": "", "salary_text": st, "salary_min": salary.annual_min(st, default_currency="INR") if st else None,
                     "source": "wellfound"})
    return rows


def fetch(urls: list[str] | None = None, limit: int = 60, **_) -> list[dict]:
    rows, seen = [], set()
    for u in (urls or [DEFAULT_URL]):
        if "wellfound.com" not in urlparse(u).netloc and "angel.co" not in urlparse(u).netloc:
            continue
        try:
            for r in parse(_http.get(u), u):
                if r["url"] not in seen:
                    seen.add(r["url"])
                    rows.append(r)
        except Exception:  # noqa: BLE001
            continue
    return rows[:limit]
