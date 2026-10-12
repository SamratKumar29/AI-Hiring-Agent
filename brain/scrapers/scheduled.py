"""Run the Kurt-Chan ai-job-scraper search+scrape stage (Firecrawl) for a profile - safe for scheduled runs.

Only its discovery half is used: scoring/cover letters are career-ops' job (Phase 5), so no LLM calls here.
Boards searched = the profile's saved `board_search` sources (hosts), else the tool's default list.
"""
import os
import sys

from brain import config, profiles
from brain.config import ROOT_DIR
from brain.sources import list_sources
from urllib.parse import urlparse

AGENT_DIR = ROOT_DIR / "ai-job-scraper"
MAX_PAGES = 12


def build_queries(name: str | None = None) -> list[str]:
    name = name or profiles.get_active()
    prefs = profiles.load_profile(name)["prefs"]
    roles = profiles.core_titles(prefs.get("target_roles") or []) or ["Software Engineer"]
    role_expr = " OR ".join(f'"{r}"' for r in roles[:5])
    loc = next((l for l in prefs.get("locations", []) if l.strip().lower() not in {"any", "anywhere", ""}), "")
    mode = str(prefs.get("work_mode", "any")).lower()
    tail = " ".join(x for x in (loc, "remote" if mode == "remote" else "") if x)
    hosts = []
    for s in list_sources("board_search", name=name):
        if s["enabled"]:
            h = urlparse(s["url"]).netloc.lower().removeprefix("www.")
            if h and h not in hosts:
                hosts.append(h)
    if not hosts:
        sys.path.insert(0, str(AGENT_DIR))
        import agent
        hosts = list(agent.load_config()["job_boards"])
    return [f"site:{h} ({role_expr}) {tail}".strip() for h in hosts]


def run(name: str | None = None, max_pages: int = MAX_PAGES) -> dict:
    """Returns {"ok", "skipped", "added", "found", "reason"}."""
    name = name or profiles.get_active()
    key = config.get("FIRECRAWL_API_KEY")
    if not key:
        return {"ok": False, "skipped": True, "added": 0, "found": 0,
                "reason": "FIRECRAWL_API_KEY is empty in brain/.env (free key at firecrawl.dev) - stage skipped"}
    os.environ["FIRECRAWL_API_KEY"] = key
    sys.path.insert(0, str(AGENT_DIR))
    import agent
    import local_sync

    agent.MAX_PAGES_TO_SCRAPE = max_pages
    try:
        jobs = agent.scrape_jobs(build_queries(name))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "skipped": False, "added": 0, "found": 0, "reason": str(e).replace(key, "***")[:300]}
    res = local_sync.save(jobs, name)
    return {"ok": True, "skipped": False, "added": res["inserted"], "found": len(jobs), "reason": ""}
