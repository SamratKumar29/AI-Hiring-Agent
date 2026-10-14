"""Application support (Goal 6): cover letter, interview prep, offer prep, follow-up, outreach.

generate(job_id, kind) runs the matching career-ops mode prompt through the central LLM (with model fallback and
output validation) using the profile's CV + the job's evaluation report + the job description.
Files: <profile>/workspace/output/prep/<job_id>/<kind>.md  (the latest version; older ones go to history/)
"""
import re
import shutil
import time
from pathlib import Path

from brain import digest, jobs_db, llm, profiles
from brain.config import ROOT_DIR

MODES = ROOT_DIR / "career-ops" / "modes"
KINDS = {
    "cover":     {"label": "Cover letter",             "mode": "cover.md",          "tokens": 3000},
    "interview": {"label": "Interview preparation",    "mode": "interview-prep.md", "tokens": 6000},
    "offer":     {"label": "Offer / negotiation prep", "mode": "offer-prep.md",     "tokens": 6000},
    "followup":  {"label": "Follow-up email",          "mode": "followup.md",       "tokens": 2500},
    "outreach":  {"label": "Outreach messages",        "mode": "contacto.md",       "tokens": 2500},
}
MIN_CHARS = 250
BAD_MARKERS = ("<function", "<parameter", "<tool_call", "</tool_call")
MAX_MODE_CHARS = 26000

PREAMBLE = (
    "IMPORTANT - ENVIRONMENT: you are in a plain text chat. You have NO tools: no file reading, no browser, no web "
    "search, no shell, no scripts. NEVER output tool calls or XML tags such as <function> or <parameter>. Everything "
    "you need (candidate CV and profile, evaluation report, job description, today's date) is in this conversation. "
    "Skip any step of the instructions below that needs files, browsing, scripts or searching, and say plainly what "
    "you could not check instead of inventing it. NEVER invent experience, numbers or facts about the candidate or the "
    "company: use only what is in the CV, profile, report and job description. "
    "This is a ONE-SHOT request: any confirmation gates, sign-offs, questions to the user or 'wait for approval' steps in the "
    "instructions are WAIVED. Do not ask questions and do not refuse; make sensible assumptions from the material given and "
    "list them in a short 'Assumptions / not verified' note at the very end. "
    "Reply with the finished deliverable in Markdown and nothing else (no preamble, no commentary about these rules)."
)

KIND_HINT = {
    "cover": "Write the cover letter now (ready to paste). One page, specific to this company and role.",
    "interview": "Produce the interview preparation document for this company and role now.",
    "offer": ("Produce the offer-stage preparation now. If an OFFER LETTER is included below, follow the contract-reading "
              "workflow. If none is included, say so in the first line and instead prepare a pre-offer negotiation brief: "
              "what to clarify, which clauses and components to look for, and questions to ask, using the candidate's "
              "stated salary expectations from the profile."),
    "followup": "Draft the follow-up message(s) now (email and a short LinkedIn variant), appropriate to the application status and elapsed time given.",
    "outreach": "Draft the outreach messages now (recruiter and hiring-manager variants), each short and specific.",
}


class PrepError(RuntimeError):
    pass


def folder(job_id: str, name: str | None = None) -> Path:
    d = profiles.workspace_path(name, "output") / "prep" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_kind(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    return KINDS[kind]


def validate(text: str) -> str | None:
    t = text.strip()
    if any(m in t for m in BAD_MARKERS):
        return "model answered with a tool call"
    if re.match(r"(?i)\W*(i can'?t|i cannot|i'm unable|i am unable|before i can|i need (you )?to)", t[:80]) or \
            re.search(r"(?i)mandatory gates|i can'?t (write|draft|produce) the", t[:400]):
        return "model refused / asked for input instead of producing the document"
    if re.search(r"(?i)can you (share|tell|confirm|provide)|please (share|confirm|provide)|shall i (proceed|continue)|"
                 r"before i (write|draft|proceed)|here.s what i found about|i couldn.t find useful|which (option|angle) would you", t[:1200]):
        return "model stopped at a confirmation gate / asked the candidate a question instead of producing the document"
    if len(t) < MIN_CHARS:
        return f"too short ({len(t)} chars)"
    return None


def _clean(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:markdown|md)?\s*\n", "", t)
    return re.sub(r"\n```\s*$", "", t).strip() + "\n"


def _tracker_note(name: str, job: dict) -> str:
    from brain import reports
    num = reports.report_number(job.get("report_path") or "")
    row = next((r for r in digest.read_tracker(name) if r.get("report_number") == num), None) if num else None
    if row:
        return f"Tracker: status {row.get('status')}, evaluated {row.get('date')}, notes: {row.get('notes') or '-'}"
    return f"Tracker: status {job['decision']}" + (f" (since {job['decided_at']})" if job.get("decided_at") else "")


def build_messages(job: dict, kind: str, name: str, extra: str = "") -> list[dict]:
    spec = _check_kind(kind)
    mode = (MODES / spec["mode"]).read_text(encoding="utf-8")[:MAX_MODE_CHARS]
    writing = (MODES / "_writing.md").read_text(encoding="utf-8") if (MODES / "_writing.md").exists() else ""
    cv, prof, narrative = (profiles.read_file(name, f) for f in ("cv.md", "profile.yml", "_profile.md"))
    report = ""
    rp = job.get("report_path")
    if rp and Path(rp).exists():
        report = Path(rp).read_text(encoding="utf-8")[:14000]
    jd = job.get("description") or ""
    system = "\n\n".join([PREAMBLE, "=== MODE INSTRUCTIONS ===", mode, "=== WRITING GUARDRAILS ===", writing,
                          "=== CANDIDATE PROFILE (YAML) ===", prof, "=== CANDIDATE NARRATIVE ===", narrative,
                          "=== CANDIDATE CV ===", cv])
    user = "\n".join([
        f"Today's date: {time.strftime('%Y-%m-%d')}",
        f"Company: {job.get('company') or 'unknown'}", f"Role: {job.get('title') or 'unknown'}",
        f"Location: {job.get('location') or 'unknown'}", f"Posting URL: {job['url']}", _tracker_note(name, job), "",
        "=== EVALUATION REPORT ===", report or "(no evaluation report yet - rely on the job description and CV)", "",
        "=== JOB DESCRIPTION ===", jd[:12000] or "(no description captured)", "",
        ("=== EXTRA INPUT FROM THE CANDIDATE ===\n" + extra.strip() + "\n") if extra.strip() else "",
        KIND_HINT[kind]])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate(job_id: str, kind: str, name: str | None = None, extra: str = "", timeout: int = 240) -> dict:
    """-> {"ok", "path", "text", "model", "error"}  (never raises for model trouble)"""
    name = name or profiles.get_active()
    spec = _check_kind(kind)
    from brain import budget
    try:
        budget.require()
    except budget.BudgetExceeded as e:
        return {"ok": False, "path": None, "text": None, "model": None, "error": str(e)}
    job = jobs_db.get_job(job_id, name)
    if not job:
        raise KeyError(f"No job '{job_id}'")
    if len(job.get("description") or "") < 700:                    # thin teaser: get the full posting first
        from brain import rank
        full = rank._fulltext(job["url"])
        if full:
            jobs_db.update_fields(job_id, name, description=full)
            job = {**job, "description": full}
    try:
        text, model = llm.chat(build_messages(job, kind, name, extra), max_tokens=spec["tokens"], timeout=timeout, validate=validate)
    except llm.LLMUnavailable as e:
        return {"ok": False, "error": "; ".join(f"{k}: {v}" for k, v in list(e.errors.items())[:3]), "path": None, "text": "", "model": None}
    text = _clean(text)
    path = folder(job_id, name) / f"{kind}.md"
    archive(path)
    path.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(path), "text": text, "model": model, "error": None}


def archive(path: Path) -> None:
    """Keep the previous version in history/ before overwriting."""
    if path.exists() and path.read_text(encoding="utf-8").strip():
        hist = path.parent / "history"
        hist.mkdir(exist_ok=True)
        shutil.copy2(path, hist / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.md")


def read(job_id: str, kind: str, name: str | None = None) -> str | None:
    _check_kind(kind)
    p = folder(job_id, name) / f"{kind}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def save_edit(job_id: str, kind: str, text: str, name: str | None = None) -> Path:
    """The user edited the document in the UI: keep the old version, store the new one."""
    _check_kind(kind)
    p = folder(job_id, name) / f"{kind}.md"
    archive(p)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return p


def list_prep(job_id: str, name: str | None = None) -> dict:
    d = folder(job_id, name)
    return {k: str(d / f"{k}.md") for k in KINDS if (d / f"{k}.md").exists()}


def mark_applied(job_id: str, name: str | None = None, notes: str | None = None) -> dict:
    """Menu item 'I applied': sets the decision and syncs the career-ops tracker."""
    name = name or profiles.get_active()
    job = jobs_db.set_decision(job_id, "applied", notes or "marked applied", name)
    return {"job": job, "sync": digest.sync_status(name)}


def resolve(ref: str, name: str | None = None) -> dict:
    """Find a job from a report number ('3' / '003'), job id, or posting URL."""
    name = name or profiles.get_active()
    ref = ref.strip()
    j = jobs_db.get_job(ref, name)
    if j:
        return j
    if re.fullmatch(r"\d{1,4}", ref):
        from brain import reports
        for job in jobs_db.list_jobs(ranked=True, limit=1_000_000, name=name):
            if reports.report_number(job["report_path"] or "") == int(ref):
                return job
        raise PrepError(f"No evaluated job with report number {ref}. See: hire.py show")
    if ref.startswith("http"):
        j = jobs_db.get_job(jobs_db.job_id(ref), name)
        if j:
            return j
    raise PrepError(f"Could not find a job for '{ref}'. Use a report number (see hire.py show), a job id or its URL.")
