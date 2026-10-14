"""`hire.py doctor`: one PASS / WARN / FAIL list that says whether the whole setup is healthy and how to fix it."""
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from brain import budget, config, nodeenv, profiles, schedule

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
RM = config.ROOT_DIR / "Resume-Matcher" / "apps"


def _r(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_python() -> dict:
    v = sys.version_info
    ok = v >= (3, 10)
    return _r("Python", PASS if ok else FAIL, f"{v.major}.{v.minor}.{v.micro}", "" if ok else "Install Python 3.10+ and recreate ./venv")


def check_venv() -> dict:
    ok = (config.ROOT_DIR / "venv" / "bin" / "python").exists() or (config.ROOT_DIR / "venv" / "Scripts" / "python.exe").exists()
    return _r("Virtual env (./venv)", PASS if ok else FAIL, "found" if ok else "missing", "python3 -m venv venv && ./venv/bin/pip install -r requirements.txt")


def check_node() -> dict:
    n = nodeenv.node_bin()
    return _r("Node.js >= 22", PASS if n else FAIL, n or "not found", "" if n else "nvm install 22")


def check_uv() -> dict:
    u = shutil.which("uv")
    return _r("uv (Resume-Matcher installer)", PASS if u else WARN, u or "not installed (only needed to reinstall Resume-Matcher)", "" if u else "pip install uv")


def check_env_file() -> dict:
    f = config.ENV_FILE
    if not f.exists():
        return _r("brain/.env", FAIL, "missing", "cp brain/.env.example brain/.env and paste your OpenRouter key")
    mode = f.stat().st_mode & 0o077
    if mode:
        return _r("brain/.env", WARN, "readable by other users", "chmod 600 brain/.env")
    return _r("brain/.env", PASS, "present, private")


def check_key() -> dict:
    try:
        config.api_key()
    except RuntimeError:
        return _r("OpenRouter key", FAIL, "OPENROUTER_API_KEY is empty", "paste the key into brain/.env")
    u = budget.usage()
    if u["ok"]:
        return _r("OpenRouter key", PASS, f"valid; ${u['monthly']:.2f} used this month")
    return _r("OpenRouter key", FAIL, f"could not verify ({u['error']})", "check the key and your network/proxy")


def check_budget() -> dict:
    c = budget.check()
    lim = f"limit ${c['limit']:.2f}" if c["limit"] else "no limit"
    if not c["allowed"]:
        return _r("Cost guard", FAIL, c["reason"], "raise MONTHLY_SPEND_LIMIT_USD in brain/.env")
    return _r("Cost guard", PASS, f"max {budget.max_evals()} evaluations/run, {lim}" + (f" ({c['reason']})" if c["reason"] else ""))


def check_llm() -> dict:
    from brain import health
    r = health.check()
    if r["ok"]:
        return _r("LLM call", PASS, f"{r['model_used']} answered in {r['latency_s']}s")
    return _r("LLM call", FAIL, r["error"] or "no model answered", "try again later, or run: ./venv/bin/python -m brain.health --select")


def check_models() -> dict:
    m = config.models()
    return _r("Model list", PASS if m else FAIL, f"{len(config.free_models())} free + {len(config.paid_models())} fallback" if m else "empty",
              "" if m else "set OPENROUTER_MODELS in brain/.env")


def check_career_ops() -> dict:
    node = nodeenv.node_bin()
    if not node:
        return _r("career-ops doctor", FAIL, "needs Node.js", "nvm install 22")
    try:
        p = subprocess.run([node, "doctor.mjs"], cwd=config.ROOT_DIR / "career-ops", capture_output=True, text=True, timeout=120,
                           env={**os.environ, "PATH": str(Path(node).parent) + os.pathsep + os.environ.get("PATH", "")})
    except subprocess.TimeoutExpired:
        return _r("career-ops doctor", FAIL, "timed out")
    if p.returncode == 0:
        return _r("career-ops doctor", PASS, "all checks passed")
    bad = [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith("✗")]
    return _r("career-ops doctor", FAIL, "; ".join(bad)[:200] or p.stdout[-150:], "cd career-ops && npm install")


def check_profile() -> list[dict]:
    name = profiles.get_active()
    if not name:
        return [_r("Active profile", FAIL, "none", "./venv/bin/python hire.py profile create --resume CV.md")]
    out = [_r("Active profile", PASS, name)]
    try:
        from brain import jobs_db
        path = jobs_db.db_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.execute("create table if not exists _doctor(x)")
        con.execute("insert into _doctor values (1)")
        con.rollback()
        con.execute("drop table if exists _doctor")
        con.commit()
        con.close()
        out.append(_r("jobs.db writable", PASS, f"{jobs_db.count(name=name)} jobs in {path.name}"))
    except Exception as e:  # noqa: BLE001
        out.append(_r("jobs.db writable", FAIL, str(e)[:120], "check permissions of career-ops/profile/<name>/workspace/data"))
    cv = profiles.read_file(name, "cv.md") if name else ""
    out.append(_r("Profile CV", PASS if len(cv or "") > 300 else FAIL, f"{len(cv or '')} chars", "" if len(cv or "") > 300 else "hire.py profile edit " + name))
    return out


def check_schedule() -> dict:
    c = schedule.cron_status()
    w = schedule.windows_status() if schedule.windows_available() else {"installed": False}
    if c["installed"] or w["installed"]:
        svc = schedule.cron_service_running()
        extra = " (cron service NOT running: sudo service cron start)" if c["installed"] and svc is False else ""
        return _r("Daily schedule", WARN if extra else PASS, ("cron: " + c["detail"] if c["installed"] else "Windows task") + extra)
    return _r("Daily schedule", WARN, f"not installed (daily time {config.get('DAILY_TIME', '08:00')})", "./venv/bin/python hire.py schedule install")


def check_notifications() -> list[dict]:
    out = []
    tok, chat = config.get("TELEGRAM_BOT_TOKEN"), config.get("TELEGRAM_CHAT_ID")
    out.append(_r("Telegram", PASS if tok and chat else WARN, "token and chat id set" if tok and chat else "not configured",
                  "" if tok and chat else "./venv/bin/python hire.py notify setup"))
    mail = all(config.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))
    out.append(_r("Email", PASS if mail else WARN, "configured" if mail else "not configured (optional)"))
    if not (tok and chat) and not mail:
        out[0]["detail"] += " - results will only be saved locally (hire.py show)"
    return out


def check_resume_matcher() -> list[dict]:
    py = RM / "backend" / ".venv" / "bin" / "python"
    out = [_r("Resume-Matcher backend", PASS if py.exists() else WARN, "installed" if py.exists() else "missing (tailoring still works via career-ops)",
              "" if py.exists() else "see plan.md Phase 0")]
    if py.exists():
        pw = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*"))
        out.append(_r("Resume-Matcher PDF browser", PASS if pw else WARN, "Chromium installed" if pw else "missing",
                      "" if pw else "Resume-Matcher/apps/backend/.venv/bin/python -m playwright install chromium-headless-shell"))
    fe = RM / "frontend"
    patched = "next/font/local" in (fe / "app" / "layout.tsx").read_text(errors="ignore") if (fe / "app" / "layout.tsx").exists() else False
    out.append(_r("Resume-Matcher fonts patch", PASS if patched else WARN, "self-hosted fonts" if patched else "not applied (PDF export needs Google Fonts)",
                  "" if patched else "see patches/resume-matcher/README.md"))
    return out


def check_scrapers() -> list[dict]:
    out = []
    for label, d in (("ai-job-scraper", "ai-job-scraper"), ("job-scraper", "job-scraper")):
        ok = (config.ROOT_DIR / d).is_dir() and any((config.ROOT_DIR / d).iterdir())
        out.append(_r(label, PASS if ok else FAIL, "present" if ok else "missing", "" if ok else f"git clone it into ./{d} (see plan.md Phase 0)"))
    fc = bool(config.get("FIRECRAWL_API_KEY"))
    out.append(_r("Firecrawl key", PASS if fc else WARN, "set" if fc else "not set (full job texts may be thin)", "" if fc else "add FIRECRAWL_API_KEY to brain/.env"))
    return out


def run(llm: bool = False) -> list[dict]:
    res = [check_python(), check_venv(), check_node(), check_uv(), check_env_file(), check_models(), check_key(), check_budget()]
    if llm:
        res.append(check_llm())
    res.append(check_career_ops())
    res += check_profile()
    res.append(check_schedule())
    res += check_notifications()
    res += check_scrapers()
    res += check_resume_matcher()
    return res


def summary(results: list[dict]) -> dict:
    return {s: sum(1 for r in results if r["status"] == s) for s in (PASS, WARN, FAIL)}
