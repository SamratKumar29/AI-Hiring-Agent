"""Eligibility pre-filter: cheap, deterministic checks BEFORE spending LLM tokens on a job.

Drops (marks 'dismissed' with note "auto-filter: <reason>", so nothing is lost and the user can restore it):
  * salary clearly below the profile's minimum (job's stated MAX < min_base_salary, currencies converted)
  * company/title/location (or the start of the description) contains an `exclude` term
  * location does not fit the profile's locations / work mode
  * duplicate of an already-kept job with the same company + title
Missing information is never a reason to drop: unknown salary / location / company are KEPT.
"""
import re

from brain import jobs_db, profiles, salary

VAGUE = {"any", "anywhere", "global", "worldwide", "flexible", ""}
ALIASES = [{"bangalore", "bengaluru"}, {"gurgaon", "gurugram"}, {"mumbai", "bombay", "navi mumbai"},
           {"delhi", "new delhi", "ncr", "delhi ncr"}, {"chennai", "madras"}, {"kolkata", "calcutta"},
           {"pune", "pimpri"}, {"hyderabad", "secunderabad"}]
DESC_HEAD = 400


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 +#]", " ", (s or "").lower())).strip()


def _variants(place: str) -> set[str]:
    p = _norm(place)
    for group in ALIASES:
        if p in group or any(p == g for g in group):
            return set(group)
    return {p}


def _salary_reason(job: dict, prefs: dict) -> str | None:
    minimum = prefs.get("min_base_salary")
    cur = prefs.get("currency")
    if not minimum:
        return None
    r = salary.parse_range(job.get("salary_text"), cur)
    if r:
        top = salary.convert(r["max"], r["currency"], cur)
        if top < minimum:
            return f"below_salary: {job.get('salary_text')} < {minimum:,} {cur}"
    elif job.get("salary_min"):
        if job["salary_min"] < minimum * 0.5:                       # unlabeled number: only act on a clear miss
            return f"below_salary: {job['salary_min']:,} < {minimum:,} {cur}"
    return None


def _exclude_reason(job: dict, prefs: dict) -> str | None:
    hay = " | ".join([_norm(job.get("company")), _norm(job.get("title")), _norm(job.get("location")),
                      _norm((job.get("description") or "")[:DESC_HEAD])])
    for term in prefs.get("exclude") or []:
        t = _norm(term)
        if t and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            return f"excluded: {term}"
    return None


def _location_reason(job: dict, prefs: dict) -> str | None:
    loc = _norm(job.get("location"))
    if not loc:
        return None
    mode = str(prefs.get("work_mode", "any")).lower()
    wanted = [l for l in (prefs.get("locations") or []) if _norm(l) not in VAGUE]
    accepts_remote = mode in ("remote", "hybrid", "any") or any(_norm(l) == "remote" for l in wanted)
    desc_head = _norm((job.get("description") or "")[:2000])
    is_remote = "remote" in loc or "anywhere" in loc or "worldwide" in loc
    if is_remote:
        return None if accepts_remote else "location: remote role but profile wants on-site"
    if mode == "remote" and "remote" not in desc_head:
        return f"location: '{job.get('location')}' is not remote"
    places = [l for l in wanted if _norm(l) != "remote"]
    if not places:
        return None
    country = _norm(prefs.get("country"))
    for place in places:
        if any(v in loc for v in _variants(place)):
            return None
    if country and country not in VAGUE and country in loc and len(country) > 2:
        return None
    return f"location: '{job.get('location')}' not in {', '.join(places)}"


def evaluate(job: dict, prefs: dict) -> str | None:
    """Return None to keep, or a short reason string to drop."""
    return _salary_reason(job, prefs) or _exclude_reason(job, prefs) or _location_reason(job, prefs)


def _dup_key(job: dict) -> tuple[str, str] | None:
    c, t = _norm(job.get("company")), _norm(job.get("title"))
    return (c, t) if c and t else None


def apply(name: str | None = None, dry_run: bool = False) -> dict:
    """Filter the profile's undecided, not-yet-synced jobs.
    -> {"kept": [job_id...], "dropped": [{"job_id","title","company","reason"}], "by_reason": {...}}"""
    name = name or profiles.get_active()
    prefs = profiles.load_profile(name)["prefs"]
    todo = jobs_db.unsynced(name)
    todo_ids = {j["job_id"] for j in todo}
    seen = {}
    for j in jobs_db.list_jobs(limit=1_000_000, name=name):         # already-known jobs that stay in play
        k = _dup_key(j)
        if k and j["job_id"] not in todo_ids and j["decision"] != "dismissed":
            seen.setdefault(k, j["job_id"])
    kept, dropped = [], []
    for j in todo:                                                     # oldest first
        reason = evaluate(j, prefs)
        k = _dup_key(j)
        if not reason and k:
            if k in seen:
                reason = f"duplicate: same company+title as {seen[k]}"
            else:
                seen[k] = j["job_id"]
        if reason:
            dropped.append({"job_id": j["job_id"], "title": j["title"], "company": j["company"], "reason": reason})
            if not dry_run:
                jobs_db.set_decision(j["job_id"], "dismissed", f"auto-filter: {reason}", name)
        else:
            kept.append(j["job_id"])
    by = {}
    for d in dropped:
        by[d["reason"].split(":")[0]] = by.get(d["reason"].split(":")[0], 0) + 1
    return {"kept": kept, "dropped": dropped, "by_reason": by}
