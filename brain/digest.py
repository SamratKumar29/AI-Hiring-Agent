"""Ranking digest (Goal 4): turn career-ops reports + profile preferences into one ordered list.

rank_score (0-5) = career-ops score, adjusted by what career-ops does not weigh numerically:
  salary vs your minimum/preferred, hard stops, legitimacy, risk, confidence, a "Skip" verdict, remote match.
Every adjustment is returned as text in `why`, so the number is explainable in the UI.
"""
import re
import time
from pathlib import Path

from brain import jobs_db, profiles, reports, salary

# ---- decision <-> career-ops tracker status -------------------------------------------------
TO_TRACKER = {"new": "Evaluated", "liked": "Evaluated", "applied": "Applied", "interview": "Interview",
              "offer": "Offer", "rejected": "Rejected", "withdrawn": "Discarded", "dismissed": "SKIP"}
FROM_TRACKER = {"evaluated": "new", "applied": "applied", "responded": "applied", "interview": "interview",
                "offer": "offer", "hired": "offer", "rejected": "rejected", "discarded": "withdrawn", "skip": "dismissed"}
STAGE = {"new": 0, "liked": 0, "applied": 1, "interview": 2, "offer": 3}
NEGATIVE = {"rejected", "withdrawn", "dismissed"}


def blend(job: dict, rep: dict, prefs: dict) -> tuple[float, list[str]]:
    """-> (rank_score 0..5, reasons). `rep` is a reports.parse() dict."""
    base = float(rep.get("score") or 0)
    adj, why = 0.0, []

    def add(delta, text):
        nonlocal adj
        adj += delta
        why.append(f"{delta:+.1f} {text}")

    cur, minimum, preferred = prefs.get("currency"), prefs.get("min_base_salary"), prefs.get("preferred_salary")
    r = salary.parse_range(rep.get("advertised_comp") or job.get("salary_text"), cur)
    if r and minimum:
        top = salary.convert(r["max"], r["currency"], cur)
        low = salary.convert(r["min"], r["currency"], cur)
        if top < minimum:
            add(-0.5, "stated pay is below your minimum")
        elif preferred and top >= preferred:
            add(0.2, "pay reaches your preferred salary")
        elif low >= minimum:
            add(0.1, "pay meets your minimum")
    stops = rep.get("hard_stops") or []
    if stops:
        add(-0.5 * min(len(stops), 2), f"{len(stops)} hard stop(s): {stops[0][:60]}")
    leg = (rep.get("legitimacy") or "").lower()
    if "suspicious" in leg:
        add(-0.7, "posting looks suspicious")
    elif "caution" in leg:
        add(-0.2, "legitimacy: proceed with caution")
    if str(rep.get("risk_level") or "").lower() == "high":
        add(-0.3, "high risk level")
    if str(rep.get("confidence") or "").lower() == "low":
        add(-0.1, "low evaluator confidence")
    if str(rep.get("final_decision") or "").lower() == "skip":
        add(-0.5, "evaluator says skip")
    if str(prefs.get("work_mode", "")).lower() == "remote" and "remote" in f"{job.get('location') or ''} {job.get('title') or ''}".lower():
        add(0.1, "remote, as you prefer")
    return round(max(0.0, min(5.0, base + adj)), 2), why


def chance(rep: dict) -> str:
    """Rough chance of success from the evaluator's own verdict: High / Medium / Low."""
    dec = str(rep.get("final_decision") or "").lower()
    stops = rep.get("hard_stops") or []
    conf = str(rep.get("confidence") or "").lower()
    score = rep.get("score") or 0
    if stops or dec == "skip" or score < 3.0:
        return "Low"
    if dec == "apply" and conf != "low" and score >= 4.0:
        return "High"
    if score >= 4.0 and not stops:
        return "High" if conf == "high" else "Medium"
    return "Medium"


def rank_job(job_id: str, report_path, name: str | None = None) -> dict | None:
    """Parse a report, store the blended score on the job. Returns the enriched dict or None if the report is unusable."""
    name = name or profiles.get_active()
    rep = reports.parse_file(report_path)
    if not rep["ok"]:
        return None
    job = jobs_db.get_job(job_id, name)
    prefs = profiles.load_profile(name)["prefs"]
    score, why = blend(job, rep, prefs)
    jobs_db.set_rank(job_id, score, str(report_path), name)
    return {**job, **rep, "rank_score": score, "why": why, "chance": chance(rep)}


# ---- listing -----------------------------------------------------------------------------------
def top(n: int = 10, name: str | None = None, **filters) -> list[dict]:
    """Best-ranked jobs, richest first. filters = jobs_db.list_jobs filters (decision, min_score, source, text...).
    Each dict has the job row + parsed report fields + `why` + `chance` + `rank` (1-based)."""
    name = name or profiles.get_active()
    prefs = profiles.load_profile(name)["prefs"]
    filters.setdefault("decision", ["new", "liked"])
    rows = jobs_db.list_jobs(ranked=True, limit=n, name=name, order="rank_score desc", **filters)
    out = []
    for i, j in enumerate(rows, 1):
        rep = reports.parse_file(j["report_path"]) if j.get("report_path") and Path(j["report_path"]).exists() else {}
        why = blend(j, rep, prefs)[1] if rep.get("ok") else []
        out.append({**j, **{k: v for k, v in rep.items() if k not in j}, "career_ops_score": rep.get("score"),
                    "why": why, "chance": chance(rep) if rep.get("ok") else "?", "rank": i})
    return out


def _cell(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "/").strip() or "-"


def render(items: list[dict], title: str) -> str:
    lines = [f"# {title}", "", f"_{len(items)} job(s), best first. Score = career-ops fit (0-5) adjusted for your preferences._", "",
             "| # | Score | Fit | Chance | Company | Role | Location | Pay | Why it ranks here | Posting | Report |",
             "|---|-------|-----|--------|---------|------|----------|-----|-------------------|---------|--------|"]
    for it in items:
        pay = it.get("advertised_comp") or it.get("salary_text")
        rep = f"[report]({Path(it['report_path']).name})" if it.get("report_path") else "-"
        why = "; ".join(it.get("why") or []) or (it.get("final_decision") or "-")
        lines.append(f"| {it['rank']} | **{it['rank_score']:.1f}** | {_cell(it.get('career_ops_score'))} | {it.get('chance', '?')} | "
                     f"{_cell(it.get('company'))} | {_cell(it.get('title'))} | {_cell(it.get('location'))} | {_cell(pay)} | "
                     f"{_cell(why)[:140]} | [open]({it['url']}) | {rep} |")
    return "\n".join(lines) + "\n"


def write_digest(n: int = 10, name: str | None = None, **filters) -> tuple[Path, list[dict]]:
    """Save output/digests/YYYY-MM-DD.md for the profile. Returns (path, items)."""
    name = name or profiles.get_active()
    items = top(n, name, **filters)
    out = profiles.workspace_path(name, "output") / "digests"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y-%m-%d')}.md"
    path.write_text(render(items, f"Job digest - {name} - {time.strftime('%Y-%m-%d')}"), encoding="utf-8")
    return path, items


def latest_digest(name: str | None = None) -> Path | None:
    d = profiles.workspace_path(name or profiles.get_active(), "output") / "digests"
    files = sorted(d.glob("*.md")) if d.exists() else []
    return files[-1] if files else None


# ---- tracker (career-ops data/applications.md) <-> jobs.db decisions ---------------------------
def tracker_path(name: str | None = None) -> Path:
    return profiles.workspace_path(name, "data") / "applications.md"


TRACKER_HEADER = ("# Applications Tracker\n\n"
                  "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
                  "|---|------|---------|------|-------|--------|-----|--------|-------|\n")


def ensure_tracker(name: str | None = None) -> Path:
    """career-ops' merge-tracker refuses to run without an existing applications.md, so create it first."""
    p = tracker_path(name)
    if not p.exists():
        p.write_text(TRACKER_HEADER, encoding="utf-8")
    return p


def _split(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def read_tracker(name: str | None = None) -> list[dict]:
    """Rows of applications.md as dicts keyed by lower-cased header ('#','company','role','score','status','report'...)."""
    p = tracker_path(name)
    if not p.exists():
        return []
    head, rows = None, []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = _split(ln)
        if head is None:
            if cells and cells[0].lower() in ("#", "no", "num") and "status" in [c.lower() for c in cells]:
                head = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(head, cells))
        m = re.search(r"\[(\d+)\]", row.get("report", ""))
        row["report_number"] = int(m.group(1)) if m else (int(row["#"]) if row.get("#", "").isdigit() else None)
        rows.append(row)
    return rows


def _set_tracker_status(name: str | None, report_number: int, new_status: str) -> bool:
    p = tracker_path(name)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    head, changed = None, False
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("|"):
            continue
        cells = _split(ln)
        if head is None:
            if cells and cells[0].lower() in ("#", "no", "num") and "status" in [c.lower() for c in cells]:
                head = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: ") or len(cells) != len(head):
            continue
        row = dict(zip(head, cells))
        m = re.search(r"\[(\d+)\]", row.get("report", ""))
        num = int(m.group(1)) if m else (int(row["#"]) if row.get("#", "").isdigit() else None)
        if num == report_number and row.get("status") != new_status:
            cells[head.index("status")] = new_status
            lines[i] = "| " + " | ".join(cells) + " |\n"
            changed = True
    if changed:
        p.write_text("".join(lines), encoding="utf-8")
    return changed


def sync_status(name: str | None = None) -> dict:
    """Make jobs.db decisions and the career-ops tracker agree. Rule: a negative outcome (rejected / withdrawn /
    dismissed) wins; otherwise the furthest stage wins (Evaluated < Applied < Interview < Offer).
    -> {"to_db": n, "to_tracker": n}"""
    name = name or profiles.get_active()
    res = {"to_db": 0, "to_tracker": 0}
    if not tracker_path(name).exists():
        return res
    by_num = {r["report_number"]: r for r in read_tracker(name) if r["report_number"] is not None}
    for job in jobs_db.list_jobs(ranked=True, limit=1_000_000, name=name):
        num = reports.report_number(job["report_path"] or "")
        row = by_num.get(num)
        if not row:
            continue
        t_dec = FROM_TRACKER.get(row.get("status", "").strip().lower())
        if t_dec is None:
            continue
        d_dec = job["decision"]
        if t_dec == d_dec or (t_dec == "new" and d_dec == "liked"):
            continue
        d_neg, t_neg = d_dec in NEGATIVE, t_dec in NEGATIVE
        if d_neg and not t_neg:
            winner = "db"
        elif t_neg and not d_neg:
            winner = "tracker"
        elif d_neg and t_neg:
            winner = "db"
        else:
            winner = "tracker" if STAGE[t_dec] > STAGE[d_dec] else "db"
        if winner == "tracker":
            jobs_db.set_decision(job["job_id"], t_dec, "synced from career-ops tracker", name)
            res["to_db"] += 1
        elif _set_tracker_status(name, num, TO_TRACKER[d_dec]):
            res["to_tracker"] += 1
    return res


# ---- phone-friendly text (Telegram / email) ------------------------------------------------------
def render_text(items: list[dict], header: str = "", footer: str = "") -> str:
    """Plain text, one block per job, no tables (tables are unreadable on a phone)."""
    parts = [header.strip()] if header.strip() else []
    for it in items:
        pay = it.get("advertised_comp") or it.get("salary_text")
        meta = " | ".join(x for x in (it.get("location"), pay) if x)
        lines = [f"{it['rank']}. {it['rank_score']:.1f}/5 [{it.get('chance', '?')}] {it.get('company') or '?'} - {it.get('title') or '?'}"]
        if meta:
            lines.append(f"   {meta}")
        if it.get("why"):
            lines.append(f"   {'; '.join(it['why'])[:140]}")
        lines.append(f"   {it['url']}")
        parts.append("\n".join(lines))
    if footer.strip():
        parts.append(footer.strip())
    return "\n\n".join(parts)
