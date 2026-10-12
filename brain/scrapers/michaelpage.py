"""Michael Page (any country site, e.g. michaelpage.co.in) - server-rendered job tiles on listing pages."""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from brain.scrapers import _http

DEFAULT_URL = "https://www.michaelpage.co.in/jobs/technology"


def parse(html: str, base: str = DEFAULT_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tile in soup.select("div.job-tile"):
        a = tile.select_one(".job-title a[href]")
        if not a:
            continue
        loc = tile.select_one(".job-location")
        summ = tile.select_one(".job_advert__job-summary-text")
        bullets = [li.get_text(" ", strip=True) for li in tile.select(".job_advert__job-desc-bullet-points li")]
        desc = "\n".join(x for x in [summ.get_text(" ", strip=True) if summ else "", *("- " + b for b in bullets)] if x)
        ctype = tile.select_one(".job-contract-type")
        rows.append({"url": urljoin(base, a["href"]), "title": a.get_text(strip=True), "company": "Michael Page (client confidential)",
                     "location": loc.get_text(" ", strip=True) if loc else None, "description": desc,
                     "salary_text": "", "source": "michaelpage",
                     "_contract": ctype.get_text(" ", strip=True) if ctype else None})
    return rows


def fetch(urls: list[str] | None = None, pages: int = 2, limit: int = 60, **_) -> list[dict]:
    rows, seen = [], set()
    for u in (urls or [DEFAULT_URL]):
        if "michaelpage." not in urlparse(u).netloc:
            continue
        for p in range(pages):
            page_url = u if p == 0 else f"{u}{'&' if '?' in u else '?'}page={p}"
            try:
                got = parse(_http.get(page_url), page_url)
            except Exception:  # noqa: BLE001
                break
            new = [r for r in got if r["url"] not in seen]
            if not new:
                break
            seen.update(r["url"] for r in new)
            rows += new
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[:limit]]
