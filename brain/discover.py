"""Discovery pipeline (Goal 3): find jobs, filter, and queue them for career-ops. One code path for CLI, scheduler, UI.

    health -> job-scraper (manual only) -> ai-job-scraper (Firecrawl) -> board scrapers -> career-ops scan
           -> import inbox -> filter + sync to pipeline
A failing stage is reported and never stops the others.
"""
import time

from brain import jobs_db, profiles, progress, sync_pipeline

STAGES = ("health", "job-scraper", "ai-job-scraper", "boards", "career-ops-scan", "import-inbox", "sync")


def run(mode: str = "scheduled", on_stage=None, name: str | None = None, quiet: bool = False,
        scan_since_days: int = 2) -> dict:
    """mode: 'manual' (also runs the LinkedIn job-scraper) or 'scheduled'. Returns a summary dict."""
    if mode not in ("manual", "scheduled"):
        raise ValueError("mode must be 'manual' or 'scheduled'")
    name = name or profiles.get_active()
    if not name:
        raise RuntimeError("No active profile. Create one first: hire.py profile create <name> --resume <file>")
    st = lambda n, s, d="": progress.stage(n, s, d, on_stage, quiet)  # noqa: E731
    out = {"profile": name, "mode": mode, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "stages": {}, "new_jobs": 0}
    before = jobs_db.count(name=name)

    def stage(sname, fn, skip_if=None):
        if skip_if:
            out["stages"][sname] = {"status": "skipped", "detail": skip_if}
            st(sname, "skipped", skip_if)
            return
        st(sname, "running")
        try:
            status, detail, data = fn()
        except Exception as e:  # noqa: BLE001
            status, detail, data = "failed", f"{type(e).__name__}: {e}"[:300], {}
        out["stages"][sname] = {"status": status, "detail": detail, **data}
        st(sname, status, detail)

    def health():
        from brain import llm
        try:
            sel = llm.select_model()
        except llm.LLMUnavailable:
            return "failed", "no LLM answered - discovery continues, ranking will need it later", {}
        return "ok", f"model {sel['model']} ({sel['tier']} tier)", {}

    def job_scraper():
        from brain.scrapers import manual
        r = manual.run(name)
        return ("ok" if r["ok"] else "failed", f"{r['added']} new" if r["ok"] else r["log_tail"][-200:], {"added": r["added"]})

    def ai_scraper():
        from brain.scrapers import scheduled
        r = scheduled.run(name)
        if r["skipped"]:
            return "skipped", r["reason"], {}
        return ("ok" if r["ok"] else "failed", f"{r['found']} found, {r['added']} new" if r["ok"] else r["reason"], {"added": r["added"]})

    def boards():
        from brain.scrapers import boards as b
        r = b.run(name)
        bad = {k: v["error"] for k, v in r["boards"].items() if v["error"]}
        detail = ", ".join(f"{k}:{v['added']}" for k, v in r["boards"].items()) or "no boards configured"
        if r["unsupported"]:
            detail += f" | not scrapable: {', '.join(r['unsupported'])}"
        return ("failed" if bad and len(bad) == len(r["boards"]) else "ok", detail + (f" | errors: {bad}" if bad else ""), {"added": r["added"]})

    def scan():
        from brain.scrapers import career_ops_scan
        r = career_ops_scan.scan(name, since_days=scan_since_days)
        return ("ok" if r["ok"] else "failed", "scan finished" if r["ok"] else r["log_tail"][-250:], {})

    def imp():
        from brain.scrapers import career_ops_scan
        r = career_ops_scan.import_inbox(name)
        return "ok", f"{r['imported']} inbox entries added to the job list", {}

    def sync():
        r = sync_pipeline.run(name)
        reasons = ", ".join(f"{k}:{v}" for k, v in r["by_reason"].items())
        return "ok", f"{r['added']} queued for ranking, {r['filtered_out']} filtered out" + (f" ({reasons})" if reasons else ""), r

    stage("health", health)
    stage("job-scraper", job_scraper, skip_if=None if mode == "manual" else "manual runs only")
    stage("ai-job-scraper", ai_scraper)
    stage("boards", boards)
    stage("career-ops-scan", scan)
    stage("import-inbox", imp)
    stage("sync", sync)
    out["new_jobs"] = jobs_db.count(name=name) - before
    out["queued"] = out["stages"]["sync"].get("added", 0)
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return out
