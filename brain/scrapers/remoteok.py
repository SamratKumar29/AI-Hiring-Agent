"""RemoteOK - public JSON API (https://remoteok.com/api). Returns ALL recent remote jobs, so we filter by role words."""
import re

from bs4 import BeautifulSoup

from brain import salary
from brain.scrapers import _http

API = "https://remoteok.com/api"


def _text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n").strip()


def parse(data: list, keywords: list[str] | None = None, limit: int = 50) -> list[dict]:
    kws = [k.lower() for k in (keywords or []) if k]
    rows = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        hay = " ".join([j.get("position", ""), " ".join(j.get("tags") or [])]).lower()
        if kws and not any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", hay) for k in kws):
            continue
        lo, hi = int(j.get("salary_min") or 0), int(j.get("salary_max") or 0)
        st = f"${lo:,} - ${hi:,}" if lo and hi else (f"${lo:,}" if lo else "")
        rows.append({"url": (j.get("url") or j.get("apply_url") or "").strip(), "title": j["position"],
                     "company": j.get("company"), "location": j.get("location") or "Remote",
                     "description": _text(j.get("description")), "salary_text": st,
                     "salary_min": salary.annual_min(st) if st else None, "source": "remoteok",
                     "found_at": (j.get("date") or "")[:19].replace("T", " ") or None})
        if len(rows) >= limit:
            break
    return rows


def keywords_from_roles(roles: list[str]) -> list[str]:
    """['AI Engineer','ML Engineer'] -> ['ai engineer','ml engineer','ai','ml'] (role phrases first, then single words)."""
    phrases = [r.lower() for r in roles]
    words = {w for r in phrases for w in re.findall(r"[a-z+#.]{2,}", r) if w not in {"engineer", "developer", "manager", "and", "the", "of"}}
    return phrases + sorted(words)


def fetch(roles: list[str], limit: int = 50, **_) -> list[dict]:
    return parse(_http.get(API, as_json=True), keywords_from_roles(roles), limit)
