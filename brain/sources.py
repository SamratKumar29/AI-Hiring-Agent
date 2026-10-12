"""Per-profile job sources (Goal 2): board searches, single postings, company career pages.

Stored in career-ops/profile/<name>/sources.json.  add() classifies every link and ROUTES it:
  single_posting  -> the profile's career-ops inbox (data/pipeline.md)             routed = "pipeline"
  company_careers -> portals.yml tracked_companies (known ATS only)                routed = "portals"
  board_search    -> kept for the Phase-4 board scrapers                           routed = "board"
  unknown / custom careers page -> stored (unknown is disabled until you set a type) routed = "" / "unsupported"
"""
import hashlib
import json
import time

from brain import ingest_links, pipeline_inbox, portals_edit, profiles

TYPES = ("single_posting", "board_search", "company_careers", "unknown")


def _file(name: str | None):
    name = name or profiles.get_active()
    if not name:
        raise RuntimeError("No active profile. Create or activate one first.")
    profiles.load_profile(name)
    return name, profiles._dir(name) / "sources.json"


def _load(name):
    n, f = _file(name)
    try:
        return n, f, json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return n, f, {"version": 1, "sources": []}


def _save(f, data):
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def source_id(url: str) -> str:
    return hashlib.sha1(ingest_links.normalize_url(url).encode()).hexdigest()[:10]


def preview(items, name: str | None = None) -> list[dict]:
    """Extract + classify links WITHOUT saving (what the UI shows before 'Add')."""
    _, _, data = _load(name)
    have = {s["id"] for s in data["sources"]}
    out = []
    for item in [items] if isinstance(items, (str, bytes)) or hasattr(items, "__fspath__") else list(items):
        for c in ingest_links.extract_and_classify(item):
            out.append({**c, "id": source_id(c["url"]), "already_added": source_id(c["url"]) in have})
    seen, uniq = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"])
            uniq.append(c)
    return uniq


def _route(src: dict, name: str) -> str:
    try:
        if src["type"] == "single_posting":
            r = pipeline_inbox.add([{"url": src["url"], "company": src.get("company") or ""}], name)
            return "pipeline" if r["added"] else "pipeline (already there)"
        if src["type"] == "company_careers":
            if src.get("ats") not in portals_edit.ROUTABLE_ATS:
                return "unsupported: custom careers page (covered by the board scrapers, not the ATS scanner)"
            r = portals_edit.add_companies([{"name": src.get("company") or "", "careers_url": src["url"],
                                             "ats": src["ats"]}], name)
            return "portals" if r["added"] or r["duplicates"] else "unsupported"
        if src["type"] == "board_search":
            return "board"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"
    return ""


def add(items, name: str | None = None, route: bool = True, force_type: str | None = None) -> dict:
    """items: URL / pasted text / file path (txt, md, csv, html, pdf, docx) or a list of those."""
    if force_type and force_type not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    n, f, data = _load(name)
    have = {s["id"] for s in data["sources"]}
    res = {"added": [], "duplicates": [], "found": 0}
    for c in preview(items, n):
        res["found"] += 1
        if c["id"] in have:
            res["duplicates"].append(c["url"])
            continue
        typ = force_type or c["type"]
        src = {"id": c["id"], "url": c["url"], "type": typ, "board": c["board"], "ats": c["ats"],
               "company": c["company"], "added": time.strftime("%Y-%m-%d %H:%M"), "enabled": typ != "unknown",
               "last_status": "", "routed": "", "note": ""}
        if route and src["enabled"]:
            src["routed"] = _route(src, n)
        data["sources"].append(src)
        have.add(c["id"])
        res["added"].append(src)
    _save(f, data)
    return res


def list_sources(type: str | None = None, name: str | None = None) -> list[dict]:
    _, _, data = _load(name)
    return [s for s in data["sources"] if type in (None, s["type"])]


def _find(data, sid):
    for s in data["sources"]:
        if s["id"] == sid:
            return s
    raise KeyError(f"No source with id '{sid}'")


def set_enabled(sid: str, enabled: bool, name: str | None = None) -> dict:
    """Disabling stops future scanning: toggles the company in portals.yml, drops a still-pending posting."""
    n, f, data = _load(name)
    s = _find(data, sid)
    s["enabled"] = bool(enabled)
    if s["type"] == "company_careers" and s["routed"] == "portals":
        portals_edit.set_company_enabled(s["url"], enabled, n)
    elif s["type"] == "single_posting":
        if enabled:
            s["routed"] = _route(s, n)
        else:
            pipeline_inbox.remove_pending(s["url"], n)
            s["routed"] = ""
    elif enabled and not s["routed"]:
        s["routed"] = _route(s, n)
    _save(f, data)
    return s


def set_type(sid: str, typ: str, name: str | None = None) -> dict:
    if typ not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    n, f, data = _load(name)
    s = _find(data, sid)
    s["type"], s["enabled"] = typ, typ != "unknown"
    s["routed"] = _route(s, n) if s["enabled"] else ""
    _save(f, data)
    return s


def set_status(sid: str, status: str, name: str | None = None) -> None:
    n, f, data = _load(name)
    _find(data, sid)["last_status"] = status
    _save(f, data)


def remove(sid: str, name: str | None = None) -> dict:
    n, f, data = _load(name)
    s = _find(data, sid)
    if s["type"] == "company_careers" and s["routed"] == "portals":
        portals_edit.remove_company(s["url"], n)
    elif s["type"] == "single_posting":
        pipeline_inbox.remove_pending(s["url"], n)
    data["sources"] = [x for x in data["sources"] if x["id"] != sid]
    _save(f, data)
    return s


def sync(name: str | None = None) -> dict:
    """Re-route every enabled source that is not routed yet (e.g. after regenerating portals.yml)."""
    n, f, data = _load(name)
    res = {"routed": 0, "skipped": 0}
    for s in data["sources"]:
        if s["enabled"] and (not s["routed"] or s["routed"].startswith("error")):
            s["routed"] = _route(s, n)
            res["routed"] += 1
        else:
            res["skipped"] += 1
    _save(f, data)
    return res
