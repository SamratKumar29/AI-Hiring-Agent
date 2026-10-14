"""Background tasks with a run history: used by the UI (start/cancel/tail) and recorded for CLI + cron runs too.

Each run lives in <profile>/workspace/data/runs/<run_id>/ with
    status.json  {run_id, kind, profile, state, started, finished, exit_code, pid, stages, last_line, argv}
    log.txt      everything the task printed
state: queued | running | succeeded | failed | cancelled.   Stage lines: "[stage] <name> <status> <detail>".
UI tasks run through a small wrapper process (`python -m brain.taskrunner`) so they survive a browser refresh/UI restart.
"""
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from brain import config, nodeenv, profiles, progress

SINGLE_FLIGHT = ("discover", "rank", "daily")          # never run two at once (same profile)
LIVE = ("queued", "running")


class Busy(RuntimeError):
    pass


def runs_dir(profile: str | None = None) -> Path:
    d = profiles.workspace_path(profile, "data") / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(rd: Path, st: dict) -> None:
    tmp = rd / "status.json.tmp"
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(rd / "status.json")


def _read(rd: Path) -> dict | None:
    try:
        return json.loads((rd / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                    # zombie counts as dead
        return Path(f"/proc/{int(pid)}/stat").read_text().split()[2] != "Z"
    except OSError:
        return True


def _new_run(kind: str, profile: str, argv: list, pid: int | None) -> tuple[str, Path, dict]:
    rid = f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}"
    rd = runs_dir(profile) / rid
    n = 1
    while rd.exists():
        n += 1
        rid, rd = f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{n}", runs_dir(profile) / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{n}"
    rd.mkdir(parents=True)
    st = {"run_id": rid, "kind": kind, "profile": profile, "state": "running", "started": time.time(), "finished": None,
          "exit_code": None, "pid": pid, "stages": {}, "last_line": "", "argv": [str(a) for a in argv]}
    _write(rd, st)
    return rid, rd, st


def _feed(st: dict, line: str) -> None:
    line = line.rstrip("\n")
    if line.strip():
        st["last_line"] = line[:300]
    ev = progress.parse(line.split(" ", 1)[1] if line[:2].isdigit() and " [stage]" in line else line)
    if ev:
        st["stages"][ev["name"]] = {"status": ev["status"], "detail": ev["detail"], "at": time.time()}


# ------------------------------------------------------------------ queries
def get(run_id: str, profile: str | None = None) -> dict | None:
    rd = runs_dir(profile) / run_id
    st = _read(rd)
    if st and st["state"] in LIVE and not _alive(st.get("pid")):      # the process vanished without a final write
        st.update(state="failed", finished=st.get("finished") or time.time(), last_line=st["last_line"] or "process ended unexpectedly")
        _write(rd, st)
    return st


def tail(run_id: str, n: int = 40, profile: str | None = None) -> list[str]:
    f = runs_dir(profile) / run_id / "log.txt"
    if not f.exists():
        return []
    return f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def list_runs(kind: str | None = None, limit: int = 50, profile: str | None = None) -> list[dict]:
    out = []
    for rd in sorted(runs_dir(profile).iterdir(), reverse=True):
        if rd.is_dir() and (not kind or rd.name.endswith(f"-{kind}") or f"-{kind}-" in rd.name):
            st = get(rd.name, profile)
            if st and (not kind or st["kind"] == kind):
                out.append(st)
        if len(out) >= limit:
            break
    return out


def is_running(kind: str | None = None, profile: str | None = None) -> dict | None:
    for st in list_runs(kind, 20, profile):
        if st["state"] in LIVE and (kind is None or st["kind"] == kind):
            return st
    return None


def any_running(profile: str | None = None) -> dict | None:
    return is_running(None, profile)


# ------------------------------------------------------------------ UI runs
def start(kind: str, argv: list, profile: str | None = None) -> str:
    """Launch `argv` in the background. Refuses a second discover/rank/daily for the same profile."""
    profile = profile or profiles.get_active()
    if not profile:
        raise RuntimeError("No active profile.")
    if kind in SINGLE_FLIGHT:
        busy = [s for k in SINGLE_FLIGHT for s in [is_running(k, profile)] if s]
        if busy:
            raise Busy(f"A {busy[0]['kind']} run is already in progress ({busy[0]['run_id']}). Wait for it or cancel it.")
    rid, rd, st = _new_run(kind, profile, argv, None)
    st["state"] = "queued"
    env = nodeenv.with_proxy_support(dict(os.environ))
    env["AIHIRE_RUN_ID"] = rid
    p = subprocess.Popen([sys.executable, "-m", "brain.taskrunner", str(rd), "--", *[str(a) for a in argv]],
                         cwd=config.ROOT_DIR, env=env, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st.update(pid=p.pid, state="running")
    _write(rd, st)
    return rid


def cancel(run_id: str, profile: str | None = None) -> bool:
    st = get(run_id, profile)
    if not st or st["state"] not in LIVE or not st.get("pid"):
        return False
    try:
        os.killpg(int(st["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def hire_argv(*args) -> list:
    return [sys.executable, str(config.ROOT_DIR / "hire.py"), *[str(a) for a in args]]


# ------------------------------------------------------------------ wrapper process (python -m brain.taskrunner RUN_DIR -- argv...)
def _wrapper(rd: Path, argv: list) -> int:
    st = _read(rd) or {}
    st["pid"] = os.getpid()
    cancelled = {"v": False}
    child = {"p": None}

    def on_term(*_):
        cancelled["v"] = True
        if child["p"] and child["p"].poll() is None:
            child["p"].terminate()

    signal.signal(signal.SIGTERM, on_term)
    log = open(rd / "log.txt", "a", encoding="utf-8", buffering=1)
    try:
        p = subprocess.Popen(argv, cwd=config.ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             bufsize=1, stdin=subprocess.DEVNULL, errors="replace")
        child["p"] = p
        last_write = 0.0
        for line in p.stdout:
            log.write(line)
            _feed(st, line)
            if time.time() - last_write > 0.5:
                _write(rd, st)
                last_write = time.time()
        code = p.wait()
    except Exception as e:  # noqa: BLE001
        log.write(f"[taskrunner] could not run: {e}\n")
        code = 127
    st.update(finished=time.time(), exit_code=code, state="cancelled" if cancelled["v"] else ("succeeded" if code == 0 else "failed"))
    _write(rd, st)
    log.close()
    return code


# ------------------------------------------------------------------ recording runs started from the CLI / cron
class _Tee:
    def __init__(self, real, rd: Path, st: dict):
        self.real, self.log, self.st, self.buf, self.last = real, open(rd / "log.txt", "a", encoding="utf-8", buffering=1), st, "", 0.0
        self.rd = rd

    def write(self, s):
        self.real.write(s)
        self.log.write(s)
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            _feed(self.st, line)
        if time.time() - self.last > 0.5:
            _write(self.rd, self.st)
            self.last = time.time()
        return len(s)

    def flush(self):
        self.real.flush()

    def __getattr__(self, k):
        return getattr(self.real, k)


@contextlib.contextmanager
def recording(kind: str, profile: str | None = None):
    """Wrap a CLI command so it shows up in the run history (no-op when the UI already started it)."""
    profile = profile or profiles.get_active()
    if os.environ.get("AIHIRE_RUN_ID") or not profile:
        yield None
        return
    try:
        rid, rd, st = _new_run(kind, profile, sys.argv, os.getpid())
    except (OSError, FileNotFoundError, RuntimeError):
        yield None
        return
    real = sys.stdout
    sys.stdout = _Tee(real, rd, st)
    code, err = 0, None
    try:
        yield rid
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        raise
    except BaseException as e:  # noqa: BLE001
        code, err = 1, e
        raise
    finally:
        sys.stdout.flush()
        sys.stdout = real
        st.update(finished=time.time(), exit_code=code, state="succeeded" if code == 0 else "failed")
        if err:
            st["last_line"] = f"{type(err).__name__}: {err}"[:300]
        _write(rd, st)


def set_exit(code: int) -> None:
    """Let a CLI command report a non-zero result code to `recording` (call before returning from the command)."""
    raise SystemExit(code)


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(_wrapper(Path(a[0]), a[a.index("--") + 1:]))
