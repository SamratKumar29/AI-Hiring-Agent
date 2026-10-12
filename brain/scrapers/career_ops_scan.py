"""career-ops' own portal scanner (company career pages on 13 ATS systems) + import of its inbox into jobs.db."""
import re
import subprocess

from brain import jobs_db, nodeenv, pipeline_inbox, profiles
from brain.config import ROOT_DIR

CAREER_OPS = ROOT_DIR / "career-ops"
LINE_RE = re.compile(r"^- \[ \] (https?://\S+)\s*(.*)$")


def scan(name: str | None = None, since_days: int = 2, timeout: int = 900) -> dict:
    """Run `node scan.mjs --since N --quiet` for the profile. -> {"ok", "log_tail"}"""
    name = name or profiles.get_active()
    node = nodeenv.node_bin()
    if not node:
        return {"ok": False, "log_tail": "Node.js >= 22 not found (install via nvm: nvm install 22)"}
    profiles.link_active(name)                                  # career-ops reads the linked files
    p = subprocess.run([node, "scan.mjs", "--since", str(since_days), "--quiet"], cwd=CAREER_OPS,
                       env=nodeenv.env_with_node(), capture_output=True, text=True, timeout=timeout)
    return {"ok": p.returncode == 0, "log_tail": (p.stdout + p.stderr)[-1200:]}


def import_inbox(name: str | None = None) -> dict:
    """Mirror pending inbox lines into jobs.db (marked synced) so the dashboard shows them. -> {"imported": n}"""
    name = name or profiles.get_active()
    hist = pipeline_inbox.inbox_path(name).parent / "scan-history.tsv"
    scanned = set()
    if hist.exists():
        scanned = {pipeline_inbox.normalize_url(l.split("\t", 1)[0]) for l in hist.read_text(encoding="utf-8").splitlines()[1:]}
    rows = []
    for line in pipeline_inbox.pending(name):
        m = LINE_RE.match(line)
        if not m:
            continue
        url = m.group(1)
        parts = [p.strip() for p in m.group(2).split("|")[1:]] if m.group(2).strip().startswith("|") else []
        parts += [""] * 2
        clean = lambda v: v if v and v != "N/A" else None  # noqa: E731
        rows.append({"url": url, "company": clean(parts[0]), "title": clean(parts[1]),
                     "source": "career-ops scan" if pipeline_inbox.normalize_url(url) in scanned else "your links"})
    res = jobs_db.upsert_jobs(rows, name=name)
    jobs_db.mark_synced([jobs_db.job_id(r["url"]) for r in rows], name)
    return {"imported": res["inserted"]}
