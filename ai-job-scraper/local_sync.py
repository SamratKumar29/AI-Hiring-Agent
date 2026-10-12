"""Replaces kurt_chan_supabase_sync.py: save ai-job-scraper results into the profile's local jobs.db."""
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import jobs_db  # noqa: E402


def to_rows(jobs: list[dict]) -> list[dict]:
    rows = []
    for j in jobs:
        url = (j.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.")
        rows.append({"url": url, "title": j.get("title") or j.get("job_title"), "company": j.get("company"),
                     "location": j.get("location"), "description": j.get("description"),
                     "salary_text": j.get("salary"), "source": f"firecrawl:{host}"})
    return rows


def save(jobs: list[dict], profile: str | None = None) -> dict:
    return jobs_db.upsert_jobs(to_rows(jobs), name=profile)
