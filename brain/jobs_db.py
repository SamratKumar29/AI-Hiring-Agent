"""Per-profile job database (SQLite): career-ops/profile/<name>/workspace/data/jobs.db

Plain dicts/lists in and out, so the CLI, scheduler and UI all use the same functions.
"""
import hashlib
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from brain import profiles
from brain.ingest_links import classify, normalize_url

DECISIONS = ("new", "liked", "dismissed", "applied", "interview", "offer", "rejected", "withdrawn")
COLUMNS = ("job_id", "title", "company", "location", "url", "description", "salary_text", "salary_min", "source",
           "found_at", "synced_to_pipeline", "rank_score", "report_path", "decision", "notes", "decided_at")
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  job_id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
  salary_text TEXT, salary_min INTEGER, source TEXT, found_at TEXT,
  synced_to_pipeline INTEGER DEFAULT 0, rank_score REAL, report_path TEXT,
  decision TEXT DEFAULT 'new', notes TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS decision_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, decision TEXT, notes TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_jobs_decision ON jobs(decision);
CREATE INDEX IF NOT EXISTS ix_jobs_found ON jobs(found_at);
"""
ORDERS = {"rank_score desc": "rank_score IS NULL, rank_score DESC, found_at DESC",
          "found_at desc": "found_at DESC", "salary desc": "salary_min IS NULL, salary_min DESC",
          "company": "company COLLATE NOCASE, title COLLATE NOCASE", "decided_at desc": "decided_at DESC"}


def canonical_url(url: str) -> str:
    """LinkedIn/Indeed links carry tracking tokens; reduce them to the stable posting URL."""
    c = classify(url)
    return c["url"] if c["board"] in ("linkedin", "indeed") and c["type"] == "single_posting" else url.strip()


def job_id(url: str) -> str:
    return hashlib.sha1(normalize_url(canonical_url(url)).encode()).hexdigest()[:16]


def db_path(name: str | None = None) -> Path:
    return profiles.workspace_path(name, "data") / "jobs.db"


@contextmanager
def _conn(name=None):
    c = sqlite3.connect(db_path(name), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def upsert_jobs(rows: list[dict], name: str | None = None) -> dict:
    """Insert new jobs; for known jobs only fill in blank fields (never touches decision/rank/notes).
    Needs `url` (and ideally title, company). Returns {"inserted": n, "updated": n, "skipped": n}."""
    res = {"inserted": 0, "updated": 0, "skipped": 0}
    with _conn(name) as c:
        for r in rows:
            url = (r.get("url") or "").strip()
            if not url.startswith("http"):
                res["skipped"] += 1
                continue
            url = canonical_url(url)
            jid = r.get("job_id") or job_id(url)
            old = c.execute("SELECT * FROM jobs WHERE job_id=?", (jid,)).fetchone()
            vals = {k: r.get(k) for k in ("title", "company", "location", "description", "salary_text", "salary_min", "source")}
            if old is None:
                c.execute("INSERT INTO jobs(job_id,title,company,location,url,description,salary_text,salary_min,source,found_at)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (jid, vals["title"], vals["company"], vals["location"], url, vals["description"],
                           vals["salary_text"], vals["salary_min"], vals["source"], r.get("found_at") or _now()))
                res["inserted"] += 1
            else:
                fill = {k: v for k, v in vals.items() if v not in (None, "") and old[k] in (None, "")}
                if fill:
                    c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in fill)} WHERE job_id=?", (*fill.values(), jid))
                    res["updated"] += 1
                else:
                    res["skipped"] += 1
    return res


def get_job(jid: str, name: str | None = None) -> dict | None:
    with _conn(name) as c:
        r = c.execute("SELECT * FROM jobs WHERE job_id=?", (jid,)).fetchone()
        return dict(r) if r else None


def _where(decision=None, min_score=None, source=None, text=None, min_salary=None, synced=None, company=None, ranked=None):
    w, a = [], []
    if decision:
        ds = [decision] if isinstance(decision, str) else list(decision)
        w.append(f"decision IN ({','.join('?' * len(ds))})")
        a += ds
    if min_score is not None:
        w.append("rank_score >= ?")
        a.append(min_score)
    if source:
        w.append("source = ?")
        a.append(source)
    if text:
        w.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR location LIKE ?)")
        a += [f"%{text}%"] * 4
    if min_salary is not None:
        w.append("salary_min >= ?")
        a.append(min_salary)
    if synced is not None:
        w.append("synced_to_pipeline = ?")
        a.append(1 if synced else 0)
    if company:
        w.append("company LIKE ?")
        a.append(company)
    if ranked is not None:
        w.append("rank_score IS NOT NULL" if ranked else "rank_score IS NULL")
    return (" WHERE " + " AND ".join(w)) if w else "", a


def list_jobs(decision=None, min_score=None, source=None, text=None, min_salary=None, synced=None, company=None, ranked=None,
              order="rank_score desc", limit=500, offset=0, name: str | None = None) -> list[dict]:
    if order not in ORDERS:
        raise ValueError(f"order must be one of {list(ORDERS)}")
    where, args = _where(decision, min_score, source, text, min_salary, synced, company, ranked)
    with _conn(name) as c:
        rows = c.execute(f"SELECT * FROM jobs{where} ORDER BY {ORDERS[order]} LIMIT ? OFFSET ?",
                         (*args, int(limit), int(offset))).fetchall()
    return [dict(r) for r in rows]


def count(name: str | None = None, **filters) -> int:
    where, args = _where(**filters)
    with _conn(name) as c:
        return c.execute(f"SELECT COUNT(*) FROM jobs{where}", args).fetchone()[0]


def unsynced(name: str | None = None) -> list[dict]:
    """Jobs not yet handed to career-ops that are still undecided."""
    with _conn(name) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM jobs WHERE synced_to_pipeline=0 AND decision='new' ORDER BY found_at")]


def mark_synced(ids: list[str], name: str | None = None) -> int:
    with _conn(name) as c:
        n = 0
        for i in ids:
            n += c.execute("UPDATE jobs SET synced_to_pipeline=1 WHERE job_id=?", (i,)).rowcount
    return n


def set_decision(jid: str, decision: str, notes: str | None = None, name: str | None = None) -> dict:
    """Change a job's status. The change is also appended to decision_history (never deleted)."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    with _conn(name) as c:
        if not c.execute("SELECT 1 FROM jobs WHERE job_id=?", (jid,)).fetchone():
            raise KeyError(f"No job '{jid}'")
        at = _now()
        c.execute("UPDATE jobs SET decision=?, decided_at=?, notes=COALESCE(?, notes) WHERE job_id=?",
                  (decision, at, notes, jid))
        c.execute("INSERT INTO decision_history(job_id,decision,notes,at) VALUES(?,?,?,?)", (jid, decision, notes, at))
    return get_job(jid, name)


def history(jid: str, name: str | None = None) -> list[dict]:
    with _conn(name) as c:
        return [dict(r) for r in c.execute("SELECT decision,notes,at FROM decision_history WHERE job_id=? ORDER BY id", (jid,))]


def set_rank(jid: str, score: float, report_path: str | None = None, name: str | None = None) -> None:
    with _conn(name) as c:
        c.execute("UPDATE jobs SET rank_score=?, report_path=COALESCE(?, report_path) WHERE job_id=?", (score, report_path, jid))


def stats(name: str | None = None) -> dict:
    with _conn(name) as c:
        q = lambda sql: {r[0] or "?": r[1] for r in c.execute(sql)}  # noqa: E731
        return {"total": c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "by_decision": q("SELECT decision, COUNT(*) FROM jobs GROUP BY decision"),
                "by_source": q("SELECT source, COUNT(*) FROM jobs GROUP BY source"),
                "by_day": q("SELECT substr(found_at,1,10), COUNT(*) FROM jobs GROUP BY 1 ORDER BY 1 DESC LIMIT 30"),
                "unsynced": c.execute("SELECT COUNT(*) FROM jobs WHERE synced_to_pipeline=0 AND decision='new'").fetchone()[0]}


def update_fields(jid: str, name: str | None = None, **fields) -> None:
    """Overwrite descriptive fields (e.g. a fuller description fetched later). Never touches decision/rank."""
    allowed = {"title", "company", "location", "description", "salary_text", "salary_min", "notes"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if fields:
        with _conn(name) as c:
            c.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in fields)} WHERE job_id=?", (*fields.values(), jid))
