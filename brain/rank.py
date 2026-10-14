"""Rank queued jobs with career-ops' evaluator (Goal 4). One job at a time, so each report maps to exactly one job.

Per job:  full description -> jds/<id>.md -> `openrouter-runner.mjs evaluate local:jds/<id>.md` (model fallback, reply
validated) -> report parsed -> rank score stored -> tracker row written -> inbox line ticked.
After the batch: merge-tracker, status sync, digest.
"""
import shutil
import subprocess
import time
from pathlib import Path

from brain import config, digest, jobs_db, nodeenv, pipeline_inbox, profiles, progress, reports, sync_env
from brain.config import ROOT_DIR
from brain.llm import LLMUnavailable
from brain.sync_pipeline import _jd_markdown

CAREER_OPS = ROOT_DIR / "career-ops"
ADDITIONS = CAREER_OPS / "batch" / "tracker-additions"
JDS_DIR = CAREER_OPS / "jds"
THIN_DESCRIPTION = 700          # shorter than this: fetch the full posting before spending LLM tokens
FAILED_MARK = "rank-failed:"
MAX_CONSECUTIVE_OUTAGES = 2


def _fulltext(url: str) -> str | None:
    """Full posting text via Firecrawl (Indeed/Naukri/LinkedIn block plain fetches). None if unavailable."""
    key = config.get("FIRECRAWL_API_KEY")
    if not key or not url.startswith("http"):
        return None
    try:
        from firecrawl import FirecrawlApp
        md = FirecrawlApp(api_key=key).scrape(url, formats=["markdown"], only_main_content=True, timeout=60000).markdown
        return (md or "").strip()[:12000] or None
    except Exception:  # noqa: BLE001
        return None


GENERIC = {"engineer", "developer", "manager", "senior", "junior", "lead", "staff", "principal", "and", "the", "of", "related", "roles"}


SYNONYMS = [(r"machine[- ]learning", "ml"), (r"artificial[- ]intelligence", "ai"), (r"gen(?:erative)?[- ]?ai", "ai"),
            (r"large[- ]language[- ]models?", "llm"), (r"data[- ]scientist", "datascientist")]


def _norm_title(text: str) -> str:
    import re
    t = (text or "").lower()
    for pat, rep in SYNONYMS:
        t = re.sub(pat, rep, t)
    return t


def title_affinity(title: str, roles: list[str]) -> int:
    """How many of the profile's role phrases / key words appear in a job title (whole words, synonyms folded)."""
    import re
    t = _norm_title(title)
    score = 0
    for role in profiles.core_titles(roles):
        r = _norm_title(role)
        if re.search(r"(?<![a-z0-9])" + re.escape(r) + r"(?![a-z0-9])", t):
            score += 3
        for w in re.findall(r"[a-z+#.]{2,}", r):
            if w not in GENERIC and re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
                score += 1
    return score


def pick(name: str, limit: int, retry_failed: bool = False) -> list[dict]:
    """Queued, undecided, unranked jobs. Order: links the user pasted, then best title match, then newest."""
    rows = jobs_db.list_jobs(decision="new", ranked=False, synced=True, limit=1_000_000, name=name)
    if not retry_failed:
        rows = [r for r in rows if not (r["notes"] or "").startswith(FAILED_MARK)]
    roles = profiles.load_profile(name)["prefs"].get("target_roles") or []
    rows.sort(key=lambda r: r["found_at"] or "", reverse=True)
    rows.sort(key=lambda r: -title_affinity(r["title"], roles))
    rows.sort(key=lambda r: 0 if r["source"] == "your links" else 1)
    return rows[:limit]


def _quarantine_stale_additions() -> None:
    """Tracker-addition files left by crashed runs would be merged into whatever profile is active - set them aside."""
    stale = [p for p in ADDITIONS.glob("*.tsv")]
    if stale:
        (ADDITIONS / "orphaned").mkdir(exist_ok=True)
        for p in stale:
            shutil.move(str(p), str(ADDITIONS / "orphaned" / f"{int(time.time())}-{p.name}"))


def _tsv(num: int, job: dict, rep: dict, report_name: str, why_note: str) -> str:
    clean = lambda v: " ".join(str(v or "").replace("\t", " ").split()) or "?"  # noqa: E731
    return "\t".join([str(num), time.strftime("%Y-%m-%d"), clean(job["company"] or rep.get("company")),
                      clean(job["title"] or rep.get("role")), "Evaluated", f"{rep['score']:.1f}/5", "❌",
                      f"[{num:03d}](reports/{report_name})", clean(why_note)]) + "\n"


def evaluate_one(job: dict, name: str, models: list[str] | None = None, timeout: int = 600) -> dict:
    """Evaluate a single job. -> {"ok", "model", "report", "rep", "error", "unusable"} (never raises for model trouble)."""
    reports_dir = CAREER_OPS / "reports"
    reports_dir.mkdir(exist_ok=True)
    JDS_DIR.mkdir(exist_ok=True)
    if len(job["description"] or "") < THIN_DESCRIPTION:
        full = _fulltext(job["url"])
        if full:
            jobs_db.update_fields(job["job_id"], name, description=full)
            job = {**job, "description": full}
    ref = f"local:jds/{job['job_id']}.md"
    (JDS_DIR / f"{job['job_id']}.md").write_text(_jd_markdown(job), encoding="utf-8")
    before = {p.name for p in reports_dir.glob("*.md")}
    found = {}

    def check(proc, model):
        new = sorted((p for p in reports_dir.glob("*.md") if p.name not in before), key=lambda p: p.stat().st_mtime)
        if not new:
            return "unusable: no report written"
        rep = reports.parse_file(new[-1])
        if not rep["ok"]:
            for p in new:
                p.unlink(missing_ok=True)
            return "unusable: " + "; ".join(rep["problems"])
        found.update(path=new[-1], rep=rep)
        return None

    try:
        proc, model = sync_env.run_with_fallback([nodeenv.node_bin(), "openrouter-runner.mjs", "evaluate", ref],
                                                 str(CAREER_OPS), timeout=timeout, models=models, validate=check)
    except LLMUnavailable as e:
        unusable = any(str(v).startswith("unusable") for v in e.errors.values())
        return {"ok": False, "error": "; ".join(f"{k}: {v}" for k, v in list(e.errors.items())[:3]), "unusable": unusable}
    return {"ok": True, "model": model, "report": found["path"], "rep": found["rep"], "job": job, "ref": ref}


def run(name: str | None = None, max_n: int | None = None, on_progress=None, quiet: bool = False, retry_failed: bool = False,
        timeout: int = 600) -> dict:
    """-> {"ranked", "failed", "skipped_outage", "remaining", "digest", "details": [...], "status_sync": {...}}"""
    name = name or profiles.get_active()
    if not name:
        raise RuntimeError("No active profile.")
    from brain import budget
    max_n = max_n or budget.max_evals()
    budget.require()
    if not nodeenv.node_bin():
        raise RuntimeError("Node.js >= 22 not found (nvm install 22).")
    st = lambda s, d="": progress.stage("rank", s, d, on_progress, quiet)  # noqa: E731
    profiles.link_active(name)
    from brain.scrapers import career_ops_scan
    career_ops_scan.import_inbox(name)                       # pasted links -> job list
    _quarantine_stale_additions()
    todo = pick(name, max_n, retry_failed)
    out = {"ranked": 0, "failed": 0, "stopped_early": False, "remaining": 0, "details": [], "digest": None, "status_sync": {}}
    st("running", f"{len(todo)} job(s) to evaluate (max {max_n})")
    good_model, outages = None, 0
    all_models = [m for m in config.models() if not m.endswith(":batch")]
    for i, job in enumerate(todo, 1):
        label = f"{i}/{len(todo)} {job['company'] or '?'} - {job['title'] or job['url'][:50]}"
        st("running", label)
        models = ([good_model] + [m for m in all_models if m != good_model]) if good_model else None
        r = evaluate_one(job, name, models, timeout)
        for p in ADDITIONS.glob("or-*.tsv"):                 # the runner's placeholder row ("(see report)") - never keep it
            p.unlink(missing_ok=True)
        if not r["ok"]:
            out["failed"] += 1
            outages = 0 if r["unusable"] else outages + 1
            if r["unusable"]:
                jobs_db.update_fields(job["job_id"], name, notes=f"{FAILED_MARK} {time.strftime('%Y-%m-%d')} {r['error'][:150]}")
            out["details"].append({"job_id": job["job_id"], "ok": False, "error": r["error"]})
            st("running", f"{label} FAILED: {r['error'][:100]}")
            if outages >= MAX_CONSECUTIVE_OUTAGES:
                out["stopped_early"] = True
                st("running", "no model is answering right now - stopping; run again later")
                break
            continue
        outages, good_model = 0, r["model"]
        rep, report = r["rep"], r["report"]
        ranked = digest.rank_job(job["job_id"], report, name)
        num = reports.report_number(report)
        ADDITIONS.mkdir(parents=True, exist_ok=True)
        (ADDITIONS / f"{num:03d}-{job['job_id']}.tsv").write_text(
            _tsv(num, r["job"], rep, report.name, f"rank {ranked['rank_score']}; {rep.get('final_decision') or ''}".strip("; ")), encoding="utf-8")
        pipeline_inbox.mark_done(job["url"], r["ref"], name)
        out["ranked"] += 1
        out["details"].append({"job_id": job["job_id"], "ok": True, "model": r["model"], "score": rep["score"],
                               "rank_score": ranked["rank_score"], "report": report.name})
    # merge evaluated jobs into the profile's applications.md
    if any(ADDITIONS.glob("*.tsv")):
        digest.ensure_tracker(name)
        p = subprocess.run([nodeenv.node_bin(), "merge-tracker.mjs"], cwd=CAREER_OPS, env=nodeenv.env_with_node(),
                           capture_output=True, text=True, timeout=120)
        out["merge"] = {"ok": p.returncode == 0, "log": (p.stdout + p.stderr)[-300:]}
    out["status_sync"] = digest.sync_status(name)
    path, items = digest.write_digest(10, name)
    out["digest"] = str(path)
    out["remaining"] = len(pick(name, 1_000_000, retry_failed))
    st("ok" if out["ranked"] or not todo else "failed",
       f"{out['ranked']} ranked, {out['failed']} failed, {out['remaining']} still waiting")
    return out
