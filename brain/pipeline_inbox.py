"""The career-ops URL inbox (data/pipeline.md of a profile): safe, de-duplicated appends.

Format written (same as career-ops scan.mjs):  - [ ] <url> | <company> | <title>      (under '## Pending')
Cooperates with career-ops' own writers through the same lock directory convention (<file>.lock).
"""
import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from brain import profiles
from brain.ingest_links import classify, normalize_url

SKELETON = ("# Pipeline — Pending URLs\n\nPaste job URLs below as `- [ ] {url}` then run `/career-ops pipeline`.\n\n"
            "## Pending\n\n## Processed\n")
PENDING = ("## Pending", "## Pendientes")
STALE_S, TIMEOUT_S = 30, 8
URL_IN_LINE = re.compile(r"https?://[^\s|)\]]+")


def inbox_path(name: str | None = None) -> Path:
    return profiles.workspace_path(name, "data") / "pipeline.md"


@contextmanager
def _lock(path: Path):
    lock = Path(str(path) + ".lock")
    deadline = time.time() + TIMEOUT_S
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_S:        # abandoned lock
                    shutil.rmtree(lock, ignore_errors=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise TimeoutError(f"pipeline inbox is locked by another process: {lock}")
            time.sleep(0.08)
    try:
        (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "token": uuid.uuid4().hex,
                                                     "createdAt": int(time.time() * 1000), "by": "ai-hiring-agent"}))
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def known_urls(name: str | None = None) -> set[str]:
    """Normalized URLs already in the inbox (pending OR processed) or in career-ops' scan history."""
    seen: set[str] = set()
    p = inbox_path(name)
    if p.exists():
        seen |= {normalize_url(u) for u in URL_IN_LINE.findall(p.read_text(encoding="utf-8"))}
    hist = p.parent / "scan-history.tsv"
    if hist.exists():
        for line in hist.read_text(encoding="utf-8").splitlines()[1:]:
            u = line.split("\t", 1)[0]
            if u.startswith("http"):
                seen.add(normalize_url(u))
    return seen


def _field(v: str) -> str:
    return re.sub(r"\s*[|\r\n]+\s*", " ", v or "").strip()


def _line(ref: str, company: str, title: str) -> str:
    if not company and not title:
        return f"- [ ] {ref}"
    return f"- [ ] {ref} | {_field(company) or 'N/A'} | {_field(title) or 'N/A'}"


def add(entries, name: str | None = None) -> dict:
    """Append URLs to the inbox. entries: list of url strings or dicts {url, company, title, ref}.
    `ref` (optional) is written instead of the url, e.g. "local:jds/abc.md" (career-ops reads the saved text).
    Returns {"added": [url...], "duplicates": [url...], "invalid": [...]}"""
    path = inbox_path(name)
    res = {"added": [], "duplicates": [], "invalid": []}
    with _lock(path):
        seen = known_urls(name)
        existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = []
        for e in entries:
            e = {"url": e} if isinstance(e, str) else dict(e)
            url = (e.get("url") or "").strip()
            if not re.match(r"https?://[^/\s]+\.[^/\s]+", url):
                res["invalid"].append(url)
                continue
            canon = classify(url)["url"]
            ref = (e.get("ref") or "").strip()
            if canon in seen or normalize_url(url) in seen or (ref and ref in existing_text):
                res["duplicates"].append(url)
                continue
            seen.add(canon)
            seen.add(normalize_url(url))
            lines.append(_line(ref or (canon if canon.startswith("http") else url), e.get("company", ""), e.get("title", "")))
            res["added"].append(canon)
        if lines:
            text = path.read_text(encoding="utf-8") if path.exists() else SKELETON
            marker = next((m for m in PENDING if m in text), None)
            if marker is None:
                proc = text.find("\n## ")
                at = len(text) if proc == -1 else proc
                text = text[:at].rstrip("\n") + "\n\n## Pending\n\n" + "\n".join(lines) + "\n" + text[at:]
            else:
                start = text.index(marker) + len(marker)
                nxt = text.find("\n## ", start)
                at = len(text) if nxt == -1 else nxt
                head = text[:at].rstrip("\n")
                text = head + ("\n\n" if head.endswith(marker) else "\n") + "\n".join(lines) + "\n" + ("\n" + text[at:].lstrip("\n") if nxt != -1 else "")
            tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
    return res


def pending(name: str | None = None) -> list[str]:
    """Lines currently waiting under '## Pending'."""
    p = inbox_path(name)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    marker = next((m for m in PENDING if m in text), None)
    if not marker:
        return []
    start = text.index(marker) + len(marker)
    nxt = text.find("\n## ", start)
    block = text[start: nxt if nxt != -1 else len(text)]
    return [ln.strip() for ln in block.splitlines() if ln.strip().startswith("- [ ]")]


def remove_pending(url: str, name: str | None = None) -> bool:
    """Drop a still-pending line for `url` (already-processed entries are left alone)."""
    p = inbox_path(name)
    if not p.exists():
        return False
    target = normalize_url(url)
    with _lock(p):
        text = p.read_text(encoding="utf-8")
        marker = next((m for m in PENDING if m in text), None)
        if not marker:
            return False
        start = text.index(marker) + len(marker)
        nxt = text.find("\n## ", start)
        end = nxt if nxt != -1 else len(text)
        kept, removed = [], False
        for ln in text[start:end].splitlines(keepends=True):
            m = URL_IN_LINE.search(ln)
            if ln.strip().startswith("- [ ]") and m and normalize_url(m.group(0)) == target:
                removed = True
                continue
            kept.append(ln)
        if removed:
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text(text[:start] + "".join(kept) + text[end:], encoding="utf-8")
            os.replace(tmp, p)
        return removed


def mark_done(url: str, ref: str | None = None, name: str | None = None) -> bool:
    """Tick a pending inbox line (`- [ ]` -> `- [x]`) once the job was evaluated, so career-ops won't redo it."""
    p = inbox_path(name)
    if not p.exists():
        return False
    target = normalize_url(url)
    with _lock(p):
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        hit = False
        for i, ln in enumerate(lines):
            if not ln.startswith("- [ ] "):
                continue
            m = URL_IN_LINE.search(ln)
            if (m and normalize_url(m.group(0)) == target) or (ref and ln[6:].startswith(ref)):
                lines[i] = "- [x] " + ln[6:]
                hit = True
        if hit:
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text("".join(lines), encoding="utf-8")
            os.replace(tmp, p)
        return hit
