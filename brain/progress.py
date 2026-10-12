"""One machine-readable progress line per stage, shared by CLI, scheduler and UI.

    [stage] <name> <running|ok|failed|skipped> <detail>
"""
import re
import time

STATES = ("running", "ok", "failed", "skipped")
LINE_RE = re.compile(r"^\[stage\] (\S+) (running|ok|failed|skipped)(?: (.*))?$")


def stage(name: str, status: str, detail: str = "", callback=None, quiet: bool = False) -> str:
    assert status in STATES, status
    line = f"[stage] {name} {status}" + (f" {' '.join(str(detail).split())}" if detail else "")
    if not quiet:
        print(line, flush=True)
    if callback:
        callback({"name": name, "status": status, "detail": str(detail), "at": time.time()})
    return line


def parse(line: str) -> dict | None:
    m = LINE_RE.match(line.strip())
    return {"name": m.group(1), "status": m.group(2), "detail": m.group(3) or ""} if m else None
