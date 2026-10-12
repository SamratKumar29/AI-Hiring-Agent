"""Hand the profile's new jobs to career-ops: filter, then append to its inbox (data/pipeline.md).

Jobs from boards whose pages a headless browser can't read well (LinkedIn login wall, Michael Page summaries,
Wellfound) get their description saved to career-ops/jds/<job_id>.md and are queued as `local:jds/<job_id>.md`.
"""
from brain import filter as eligibility
from brain import jobs_db, pipeline_inbox, profiles
from brain.config import ROOT_DIR

JDS_DIR = ROOT_DIR / "career-ops" / "jds"
LOCAL_JD_SOURCES = {"linkedin", "michaelpage", "wellfound", "careers_future"}
MIN_JD_CHARS = 150


def _jd_markdown(j: dict) -> str:
    head = [f"# {j['title'] or 'Job'} - {j['company'] or 'Unknown company'}", "", f"**URL:** {j['url']}"]
    for label, key in (("Location", "location"), ("Salary", "salary_text"), ("Source", "source")):
        if j.get(key):
            head.append(f"**{label}:** {j[key]}")
    return "\n".join(head) + "\n\n" + (j.get("description") or "").strip() + "\n"


def run(name: str | None = None, apply_filter: bool = True, limit: int | None = None) -> dict:
    """-> {"considered", "filtered_out", "by_reason", "added", "already_in_pipeline", "local_jds"}"""
    name = name or profiles.get_active()
    res = {"considered": 0, "filtered_out": 0, "by_reason": {}, "added": 0, "already_in_pipeline": 0, "local_jds": 0}
    pending_ids = None
    if apply_filter:
        f = eligibility.apply(name)
        res["filtered_out"], res["by_reason"] = len(f["dropped"]), f["by_reason"]
        pending_ids = set(f["kept"])
    jobs = [j for j in jobs_db.unsynced(name) if pending_ids is None or j["job_id"] in pending_ids]
    if limit:
        jobs = jobs[:limit]
    res["considered"] = len(jobs)
    entries = []
    for j in jobs:
        e = {"url": j["url"], "company": j["company"] or "", "title": j["title"] or ""}
        if (j["source"] or "").split(":")[0] in LOCAL_JD_SOURCES and len(j["description"] or "") >= MIN_JD_CHARS:
            JDS_DIR.mkdir(parents=True, exist_ok=True)
            (JDS_DIR / f"{j['job_id']}.md").write_text(_jd_markdown(j), encoding="utf-8")
            e["ref"] = f"local:jds/{j['job_id']}.md"
            res["local_jds"] += 1
        entries.append(e)
    if entries:
        r = pipeline_inbox.add(entries, name)
        res["added"], res["already_in_pipeline"] = len(r["added"]), len(r["duplicates"])
        jobs_db.mark_synced([j["job_id"] for j in jobs], name)       # duplicates are already queued, so also done
    return res
