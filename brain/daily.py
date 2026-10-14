"""The daily run: health -> discover -> rank -> digest -> notify.  `hire.py daily` is a thin wrapper.

Exit codes: 0 all good | 1 finished but a stage failed or nothing was delivered | 2 no LLM answered |
            3 another run is already in progress
"""
import json
import os
import time
from pathlib import Path

from brain import config, digest, discover, llm, notify, profiles, rank

LOG_DIR = config.DATA_DIR / "logs"
LOCK = config.DATA_DIR / "daily.lock"
STALE_LOCK_S = 6 * 3600
TOP_N = 10


class Busy(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class _Lock:
    def __enter__(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    pid = int(LOCK.read_text() or 0)
                    age = time.time() - LOCK.stat().st_mtime
                except (ValueError, FileNotFoundError):
                    pid, age = 0, STALE_LOCK_S + 1
                if pid and _pid_alive(pid) and age < STALE_LOCK_S:
                    raise Busy(f"another daily run is in progress (pid {pid})")
                LOCK.unlink(missing_ok=True)                   # stale: owner died
        raise Busy("could not take the daily lock")

    def __exit__(self, *a):
        LOCK.unlink(missing_ok=True)


def _notified_path(name: str) -> Path:
    return profiles.workspace_path(name, "data") / "notified.json"


def _load_notified(name: str) -> set:
    try:
        return set(json.loads(_notified_path(name).read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_notified(name: str, ids: set) -> None:
    _notified_path(name).write_text(json.dumps(sorted(ids)))


def run(name: str | None = None, max_evals: int | None = None, send: bool = True) -> dict:
    name = name or profiles.get_active()
    if not name:
        raise RuntimeError("No active profile. Create one first: hire.py profile create <name> --resume <file>")
    if max_evals is None:
        max_evals = int(config.get("MAX_EVALS_PER_RUN", "20") or 20)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = LOG_DIR / f"daily-{time.strftime('%Y-%m-%d')}.log"
    out = {"profile": name, "exit": 0, "problems": [], "notified": {}, "log": str(logf)}

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        with logf.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def on_stage(e: dict) -> None:
        log(f"[stage] {e['name']} {e['status']} {e['detail']}".rstrip())

    def deliver(subject: str, body: str) -> dict:
        if not send:
            return {}
        res = notify.send(subject, body)
        for ch, r in res.items():
            if not r.get("skipped"):
                log(f"notify {ch}: {'ok' if r['ok'] else 'FAILED'} - {r['detail']}")
        if not notify.delivered(res):
            log("WARNING: nothing was delivered (run: hire.py notify setup)")
        return res

    try:
        lock = _Lock().__enter__()
    except Busy as e:
        log(str(e))
        out["exit"] = 3
        return out
    try:
        log(f"daily run for '{name}' (max {max_evals} evaluations)")
        try:
            sel = llm.select_model()
            log(f"LLM ok: {sel['model']} ({sel['tier']} tier)")
        except llm.LLMUnavailable as e:
            log(f"LLM unavailable: {'; '.join(f'{k}: {v}' for k, v in list(e.errors.items())[:3])}")
            out["notified"] = deliver("Job hunt: LLM unavailable", "No AI model answered this morning, so nothing was ranked. "
                                      "I will try again at the next scheduled run (or run: hire.py daily).")
            out["exit"] = 2
            return out

        d = discover.run("scheduled", on_stage=on_stage, name=name, quiet=True)
        out["discover"] = {"new_jobs": d["new_jobs"], "queued": d["queued"]}
        out["problems"] += [f"{k}: {v['detail'][:80]}" for k, v in d["stages"].items() if v["status"] == "failed" and k != "health"]

        try:
            r = rank.run(name, max_n=max_evals, on_progress=on_stage, quiet=True)
            out["rank"] = {k: r[k] for k in ("ranked", "failed", "remaining", "stopped_early")}
            if r["stopped_early"]:
                out["problems"].append("ranking stopped early: models not answering")
        except Exception as e:  # noqa: BLE001
            r = {"ranked": 0, "failed": 0, "remaining": 0, "stopped_early": False}
            out["rank"] = r
            out["problems"].append(f"rank: {type(e).__name__}: {str(e)[:100]}")
            log(f"rank crashed: {e}")

        path, _ = digest.write_digest(TOP_N, name)
        seen = _load_notified(name)
        fresh = [i for i in digest.top(60, name) if i["job_id"] not in seen][:TOP_N]
        for n, it in enumerate(fresh, 1):
            it["rank"] = n
        head = (f"Job digest - {name} - {time.strftime('%d %b %Y')}\n"
                f"{d['new_jobs']} new job(s) found, {r['ranked']} newly ranked, {r.get('remaining', 0)} still waiting for ranking.")
        foot = ("Problems: " + "; ".join(out["problems"])) if out["problems"] else ""
        if fresh:
            body = digest.render_text(fresh, head, foot)
        else:
            body = head + "\n\nNo new ranked matches today." + (f"\n\n{foot}" if foot else "")
        out["notified"] = deliver(f"Job hunt digest ({len(fresh)} new)", body)
        out["digest"] = str(path)
        if send and notify.delivered(out["notified"]):
            _save_notified(name, seen | {i["job_id"] for i in fresh})
        elif send:
            out["problems"].append("notification not delivered")
        out["sent"] = len(fresh)
        out["exit"] = 1 if out["problems"] else 0
        log(f"done: exit {out['exit']}; digest {path}")
        return out
    finally:
        lock.__exit__()
