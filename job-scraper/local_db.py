"""Drop-in replacement for the two supabase_utils functions scraper.py uses, backed by the profile's local jobs.db.

Which profile: env HIRE_PROFILE, else the active one.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import jobs_db  # noqa: E402

URL_BY_PROVIDER = {
    "linkedin": "https://www.linkedin.com/jobs/view/{id}",
    "careers_future": "https://www.mycareersfuture.gov.sg/job/{id}",
}


def _profile():
    return os.environ.get("HIRE_PROFILE") or None


def _url(job: dict) -> str:
    tpl = URL_BY_PROVIDER.get(job.get("provider"), "")
    return job.get("job_url") or (tpl.format(id=job["job_id"]) if tpl and job.get("job_id") else "")


def get_existing_jobs() -> tuple[set, set]:
    """(set of scraper job ids, set of (company, title) lower-cased) already stored."""
    ids, pairs = set(), set()
    for j in jobs_db.list_jobs(limit=1_000_000, name=_profile()):
        pairs.add(((j["company"] or "").strip().lower(), (j["title"] or "").strip().lower()))
        tail = (j["url"] or "").rstrip("/").rsplit("/", 1)[-1]
        ids.add(tail)
    return ids, pairs


def save_jobs(jobs: list) -> dict:
    rows = [{"url": _url(j), "title": j.get("job_title"), "company": j.get("company"), "location": j.get("location"),
             "description": j.get("description"), "source": j.get("provider") or "job-scraper",
             "found_at": None} for j in jobs if j.get("job_id")]
    res = jobs_db.upsert_jobs(rows, name=_profile())
    print(f"Saved to local jobs.db: {res}")
    return res
