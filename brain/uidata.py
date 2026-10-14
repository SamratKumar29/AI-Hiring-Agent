"""Small data helpers for the web UI (kept in brain/ so pages stay thin and testable)."""
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import quote_plus

from brain import budget, config, digest, jobs_db, nodeenv, profiles, schedule, tailor, taskrunner

BOARD_FORMS = {
    "linkedin": "LinkedIn", "michaelpage": "Michael Page", "multirecruit": "Multi Recruit", "indeed": "Indeed",
    "naukri": "Naukri", "wellfound": "Wellfound", "remoteok": "RemoteOK",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def board_search_url(board: str, keywords: str, location: str = "") -> str:
    """Build a search URL for a job board from keywords + location (a starting point you can edit before saving)."""
    kw, loc = keywords.strip(), location.strip()
    if not kw:
        raise ValueError("Enter at least one keyword.")
    if board == "linkedin":
        return f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(kw)}" + (f"&location={quote_plus(loc)}" if loc else "")
    if board == "indeed":
        return f"https://in.indeed.com/jobs?q={quote_plus(kw)}" + (f"&l={quote_plus(loc)}" if loc else "")
    if board == "naukri":
        return f"https://www.naukri.com/{_slug(kw)}-jobs" + (f"-in-{_slug(loc)}" if loc else "")
    if board == "wellfound":
        return f"https://wellfound.com/role/l/{_slug(kw)}/{_slug(loc) or 'india'}"
    if board == "remoteok":
        return f"https://remoteok.com/remote-{_slug(kw)}-jobs"
    if board == "michaelpage":
        return f"https://www.michaelpage.co.in/jobs?search={quote_plus(kw)}" + (f"&location={quote_plus(loc)}" if loc else "")
    if board == "multirecruit":
        return f"https://www.multirecruit.com/jobs?q={quote_plus(kw)}" + (f"&l={quote_plus(loc)}" if loc else "")
    raise ValueError(f"Unknown board '{board}'")


_STOP = set("the and for with that this from will have are you our your their they who what about into over more than "
            "work team role years year experience ability strong good including using such other also able must should "
            "etc per not can any all new one two job join".split())


def _words(text: str) -> set:
    return {w.rstrip(".-") for w in re.findall(r"[a-z][a-z0-9+#.\-]{2,}", (text or "").lower()) if w.rstrip(".-") not in _STOP}


def keyword_match(jd: str, cv: str, top: int = 40) -> dict:
    """Which important job-description words appear in the CV and which do not (rough, to guide editing)."""
    jd_words = [w.rstrip(".-") for w in re.findall(r"[a-z][a-z0-9+#.\-]{2,}", (jd or "").lower())]
    freq: dict = {}
    for w in jd_words:
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=lambda w: (-freq[w], w))[:top]
    cvw = _words(cv)
    return {"found": [w for w in ranked if w in cvw], "missing": [w for w in ranked if w not in cvw]}


def kpis(name: str | None = None) -> dict:
    name = name or profiles.get_active()
    s = jobs_db.stats(name)
    d = s["by_decision"]
    today = time.strftime("%Y-%m-%d")
    return {"total": s["total"], "new_today": s["by_day"].get(today, 0), "ranked": jobs_db.count(name=name, ranked=True),
            "waiting": jobs_db.count(name=name, ranked=False, decision="new"), "liked": d.get("liked", 0),
            "applied": d.get("applied", 0), "interviews": d.get("interview", 0) + d.get("offer", 0)}


def followups_due(name: str | None = None) -> list[dict]:
    """Applications whose follow-up is due, from career-ops' own cadence logic. [] when there is nothing to report."""
    name = name or profiles.get_active()
    node = nodeenv.node_bin()
    if not node or not name:
        return []
    try:
        profiles.link_active(name)
        p = subprocess.run([node, "followup-cadence.mjs", "--overdue-only"], cwd=config.ROOT_DIR / "career-ops",
                           env=nodeenv.env_with_node(), capture_output=True, text=True, timeout=60)
        data = json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    rows = data.get("entries") or data.get("overdue") or data.get("results") or [] if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)]


def next_run_text() -> str:
    c = schedule.cron_status()
    w = schedule.windows_status() if schedule.windows_available() else {"installed": False}
    if c["installed"] or w["installed"]:
        return f"daily at {config.get('DAILY_TIME', '20:00')} ({'cron' if c['installed'] else 'Windows Task Scheduler'})"
    return "not scheduled"


def needs_attention(name: str | None = None) -> list[dict]:
    """[{level: error|warning|info, text, page}] shown on the Home page."""
    out = []
    try:
        config.api_key()
    except RuntimeError:
        out.append({"level": "error", "text": "OpenRouter key is missing.", "page": "Setup"})
    if not name:
        out.append({"level": "error", "text": "No profile yet - create one to start.", "page": "Profiles"})
        return out
    runs = taskrunner.list_runs("daily", 1, name)
    if runs and runs[0]["state"] == "failed":
        out.append({"level": "warning", "text": f"The last daily run failed: {runs[0]['last_line'][:120]}", "page": "Logs"})
    if not (config.get("TELEGRAM_BOT_TOKEN") and config.get("TELEGRAM_CHAT_ID")):
        out.append({"level": "info", "text": "Telegram is not set up - results are only shown here.", "page": "Setup"})
    if next_run_text() == "not scheduled":
        out.append({"level": "info", "text": "The daily run is not scheduled.", "page": "Schedule"})
    import glob
    if (config.ROOT_DIR / "Resume-Matcher" / "apps" / "backend" / ".venv").exists() and \
            not glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*")):
        out.append({"level": "warning", "text": "Resume-Matcher's PDF browser (Chromium) is not installed.", "page": "Setup"})
    if jobs_db.count(name=name, ranked=False, decision="new"):
        out.append({"level": "info", "text": f"{jobs_db.count(name=name, ranked=False, decision='new')} job(s) are waiting to be ranked.", "page": "Run"})
    c = budget.check()
    if not c["allowed"]:
        out.append({"level": "error", "text": c["reason"], "page": "Setup"})
    return out


def resumes_for_job(job_id: str, name: str | None = None) -> list[dict]:
    d = tailor.out_dir(job_id, name)
    rows = []
    for f in sorted(d.glob("*.pdf")):
        rows.append({"engine": f.stem, "path": str(f), "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)),
                     "size_kb": round(f.stat().st_size / 1024)})
    return rows


def timeline(job_id: str, name: str | None = None) -> list[dict]:
    return jobs_db.history(job_id, name)


# ---------------------------------------------------------------- profile export / import / backups
def export_profile(name: str, dest: Path) -> Path:
    """Zip a profile folder (preferences, files, jobs.db, reports, outputs)."""
    d = profiles.load_profile(name)["dir"]
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in d.rglob("*"):
            if f.is_file() and "runs" not in f.relative_to(d).parts:
                z.write(f, Path(name) / f.relative_to(d))
    return dest


def import_profile(zip_path, new_name: str | None = None) -> str:
    """Restore a profile from export_profile's zip; returns the profile name used."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        top = {n.split("/")[0] for n in names}
        if len(top) != 1 or f"{next(iter(top))}/preferences.json" not in names:
            raise ValueError("This zip is not an exported profile (no preferences.json).")
        for n in names:                                       # no path tricks
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError("Unsafe path in zip.")
        name = profiles.slug(new_name or next(iter(top)))
        if name in profiles.list_profiles():
            raise FileExistsError(f"A profile named '{name}' already exists - choose another name.")
        target = profiles.PROFILES_DIR / name
        tmp = profiles.PROFILES_DIR / f".import-{name}"
        shutil.rmtree(tmp, ignore_errors=True)
        z.extractall(tmp)
        shutil.move(str(tmp / next(iter(top))), str(target))
        shutil.rmtree(tmp, ignore_errors=True)
    return name


def list_backups() -> list[dict]:
    root = config.DATA_DIR / "backups"
    out = []
    if root.exists():
        for stamp in sorted(root.iterdir(), reverse=True)[:60]:
            for f in stamp.iterdir():
                out.append({"when": stamp.name, "file": f.name, "path": str(f)})
    return out


def restore_backup(path: str, name: str) -> None:
    """Copy a backed-up profile file (<profile>-<file>) back into the profile via the validating writer."""
    f = Path(path)
    fname = f.name[len(name) + 1:]
    profiles.write_file(name, fname, f.read_text(encoding="utf-8"))


def log_files() -> list[Path]:
    d = config.DATA_DIR / "logs"
    return sorted(d.glob("*.log"), reverse=True) if d.exists() else []
