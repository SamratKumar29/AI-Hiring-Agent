"""
kurt_chan_supabase_sync.py

Runs AFTER Kurt-Chan/ai-job-scraper's agent.py finishes a scrape.
Reads its local output/jobs.json and upserts each job into the SAME Supabase
"jobs" table that anandanair/job-scraper uses, so career-ops has one shared
discovery inbox to pull from regardless of which scraper found a posting.

Place this file inside your Kurt-Chan/ai-job-scraper checkout (next to
agent.py) and run it as the final step of the scheduled GitHub Actions
workflow, right after `python agent.py`.

Env vars required (set as GitHub Actions secrets):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Expects output/jobs.json to be a list of objects. Kurt-Chan's own schema
varies slightly by board; this script reads defensively and fills gaps.
"""

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

JOBS_FILE = Path("output/jobs.json")

# Map Kurt-Chan's board identifiers (from config.json's job_boards) to a
# clean "source" tag stored in Supabase.
SOURCE_MAP = {
    "linkedin.com/jobs": "linkedin_kurtchan",
    "indeed.com": "indeed_kurtchan",
    "wellfound.com": "wellfound_kurtchan",
    "glassdoor.com": "glassdoor_kurtchan",
    "jobstreet.com": "jobstreet_kurtchan",
    "onlinejobs.ph": "onlinejobsph_kurtchan",
}


def infer_source(job: dict) -> str:
    url = (job.get("url") or "").lower()
    for domain, tag in SOURCE_MAP.items():
        if domain.split("/")[0] in url:
            return tag
    if "reddit.com" in url:
        return "reddit_kurtchan"
    return "unknown_kurtchan"


def stable_job_id(url: str) -> str:
    """Kurt-Chan jobs don't have LinkedIn-style numeric IDs, so derive a
    stable id from the URL so re-runs upsert instead of duplicating."""
    return "kc_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set.")
        sys.exit(1)

    if not JOBS_FILE.exists():
        logger.info(f"No {JOBS_FILE} found — nothing to sync (agent.py may have found 0 jobs).")
        return

    jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    if not jobs:
        logger.info("output/jobs.json is empty — nothing to sync.")
        return

    client = create_client(supabase_url, supabase_key)

    rows = []
    for job in jobs:
        url = job.get("url")
        if not url:
            logger.warning(f"Skipping job with no url: {job.get('title', '?')}")
            continue
        rows.append(
            {
                "job_id": stable_job_id(url),
                "job_url": url,
                "company": job.get("company", "Unknown"),
                "job_title": job.get("title") or job.get("job_title", "Unknown"),
                "location": job.get("location", ""),
                "description": job.get("description", ""),
                "salary_text": job.get("salary", ""),
                "source": infer_source(job),
                "status": "new",
                "job_state": "new",
                "resume_score_stage": "initial",
                "synced_to_pipeline": False,
            }
        )

    if not rows:
        logger.info("Nothing valid to sync.")
        return

    # Upsert on job_id so re-running a scrape doesn't create duplicates.
    result = client.table("jobs").upsert(rows, on_conflict="job_id").execute()
    logger.info(f"Upserted {len(rows)} job(s) from Kurt-Chan scraper into Supabase 'jobs' table.")


if __name__ == "__main__":
    main()
