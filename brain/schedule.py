"""Install / remove / inspect the daily schedule.  Linux/WSL cron (own marked lines) and Windows Task Scheduler."""
import re
import shutil
import subprocess

from brain import config
from brain.config import ROOT_DIR

SCRIPT = ROOT_DIR / "brain" / "run_daily.sh"
BEGIN, END = "# BEGIN ai-hiring-agent", "# END ai-hiring-agent"
TASK_NAME = "AI-Hiring-Agent Daily"


def parse_time(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text or "")
    if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
        raise ValueError(f"time must look like 08:00 (24-hour), got '{text}'")
    return int(m.group(1)), int(m.group(2))


def cron_line(hhmm: str, script=SCRIPT) -> str:
    h, m = parse_time(hhmm)
    return f"{m} {h} * * * {script}"


def _crontab_read() -> str:
    p = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""          # "no crontab for user" exits 1 -> empty


def _crontab_write(text: str) -> None:
    p = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"crontab refused the update: {p.stderr.strip()}")


def strip_block(text: str) -> str:
    return re.sub(rf"{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "", text, flags=re.S)


def cron_status() -> dict:
    if not shutil.which("crontab"):
        return {"installed": False, "detail": "crontab is not installed (sudo apt install cron)"}
    m = re.search(rf"{re.escape(BEGIN)}\n(.*?)\n{re.escape(END)}", _crontab_read(), re.S)
    line = next((ln for ln in (m.group(1).splitlines() if m else []) if ln and not ln.startswith("#")), None)
    return {"installed": bool(line), "line": line, "detail": line or "no daily entry in crontab"}


def cron_install(hhmm: str | None = None) -> dict:
    hhmm = hhmm or config.get("DAILY_TIME", "08:00")
    if not shutil.which("crontab"):
        raise RuntimeError("crontab is not installed. Install it with: sudo apt install cron")
    if not SCRIPT.exists():
        raise RuntimeError(f"{SCRIPT} is missing")
    line = cron_line(hhmm)
    base = strip_block(_crontab_read()).rstrip("\n")
    new = (base + "\n\n" if base else "") + f"{BEGIN}\n{line}\n{END}\n"
    _crontab_write(new)
    return {"line": line, "time": hhmm}


def cron_remove() -> bool:
    cur = _crontab_read()
    if BEGIN not in cur:
        return False
    rest = strip_block(cur).rstrip("\n")
    _crontab_write(rest + "\n" if rest else "")
    return True


def cron_service_running() -> bool | None:
    """True/False when we can tell, None otherwise."""
    if not shutil.which("systemctl"):
        return None
    for unit in ("cron", "crond"):
        p = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
        if p.stdout.strip() == "active":
            return True
    return False


# ---- Windows Task Scheduler (from WSL, via schtasks.exe) -------------------------------------------------
def _wsl_distro() -> str:
    import os
    return os.environ.get("WSL_DISTRO_NAME", "")


def windows_available() -> bool:
    return bool(shutil.which("schtasks.exe")) and bool(_wsl_distro())


def windows_command(hhmm: str) -> list[str]:
    h, m = parse_time(hhmm)
    run = f'wsl.exe -d {_wsl_distro()} -e {SCRIPT}'
    return ["schtasks.exe", "/Create", "/F", "/SC", "DAILY", "/TN", TASK_NAME, "/ST", f"{h:02d}:{m:02d}", "/TR", run]


def windows_install(hhmm: str | None = None) -> dict:
    hhmm = hhmm or config.get("DAILY_TIME", "08:00")
    if not windows_available():
        raise RuntimeError("Windows Task Scheduler is only reachable from WSL (schtasks.exe not found).")
    p = subprocess.run(windows_command(hhmm), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"schtasks failed: {(p.stdout + p.stderr).strip()[:200]}")
    # run as soon as possible after a missed start (laptop was off at 08:00)
    ps = (f"$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
          f"Set-ScheduledTask -TaskName '{TASK_NAME}' -Settings $s | Out-Null")
    q = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return {"time": hhmm, "catch_up": q.returncode == 0, "detail": (q.stderr or "").strip()[:150]}


def windows_remove() -> bool:
    if not windows_available():
        return False
    return subprocess.run(["schtasks.exe", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True).returncode == 0


def windows_status() -> dict:
    if not windows_available():
        return {"installed": False, "detail": "not running under WSL"}
    p = subprocess.run(["schtasks.exe", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], capture_output=True, text=True)
    return {"installed": p.returncode == 0, "detail": p.stdout.strip()[:300] if p.returncode == 0 else "no task registered"}


def last_run() -> str | None:
    log = config.DATA_DIR / "logs" / "cron.log"
    if not log.exists():
        return None
    marks = [ln for ln in log.read_text(errors="replace").splitlines() if ln.startswith("===")]
    return " ".join(marks[-2:]) if marks else None
