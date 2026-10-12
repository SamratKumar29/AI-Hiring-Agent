"""Run the anandanair job-scraper (LinkedIn + Careers Future) for a profile - MANUAL runs only.

Search terms/location/work mode come from the profile's preferences; results land in the profile's jobs.db.
"""
import json
import os
import subprocess
import sys
import tempfile

from brain import profiles
from brain.config import ROOT_DIR

SCRAPER_DIR = ROOT_DIR / "job-scraper"
VAGUE = {"any", "anywhere", "remote", "global", "worldwide", ""}
WORK_MODE_CODE = {"onsite": 1, "remote": 2, "hybrid": 3}          # LinkedIn f_WT; "any" -> not sent


def build_config(name: str | None = None, per_search: int = 5) -> dict:
    name = name or profiles.get_active()
    prefs = profiles.load_profile(name)["prefs"]
    queries = profiles.core_titles(prefs.get("target_roles") or []) or ["Software Engineer"]
    location = next((l for l in prefs.get("locations", []) if l.strip().lower() not in VAGUE), None) \
        or prefs.get("city") or prefs.get("country") or ""
    cfg = {"LINKEDIN_SEARCH_QUERIES": queries, "LINKEDIN_LOCATION": location, "LINKEDIN_GEO_ID": 0,
           "LINKEDIN_F_WT": WORK_MODE_CODE.get(str(prefs.get("work_mode", "any")).lower(), 0),
           "SCRAPING_SOURCES": ["linkedin"], "MAX_JOBS_PER_SEARCH": {"linkedin": per_search, "careers_future": per_search},
           "CAREERS_FUTURE_SEARCH_QUERIES": queries}
    if "singapore" in (location + " " + str(prefs.get("country", ""))).lower():
        cfg["SCRAPING_SOURCES"].append("careers_future")
    return cfg


def run(name: str | None = None, per_search: int = 5, timeout: int = 1800) -> dict:
    """Returns {"ok": bool, "added": int, "log_tail": str}."""
    from brain import jobs_db

    name = name or profiles.get_active()
    before = jobs_db.count(name=name)
    cfg = build_config(name, per_search)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(cfg, f)
    env = {**os.environ, "HIRE_PROFILE": name, "HIRE_SCRAPER_CONFIG": f.name}
    try:
        p = subprocess.run([sys.executable, "scraper.py"], cwd=SCRAPER_DIR, env=env, capture_output=True,
                           text=True, timeout=timeout)
        ok, tail = p.returncode == 0, (p.stdout + p.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        ok, tail = False, f"timed out after {timeout}s"
    finally:
        os.unlink(f.name)
    return {"ok": ok, "added": jobs_db.count(name=name) - before, "log_tail": tail, "config": cfg}
