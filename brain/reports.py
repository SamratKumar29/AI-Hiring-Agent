"""Parse career-ops evaluation reports (reports/NNN-company-date.md) into plain dicts."""
import re
from pathlib import Path

import yaml

SCORE_RE = re.compile(r"\*\*Score:\*\*\s*\**\s*(\d+(?:\.\d+)?)\s*(?:/\s*5)?", re.I)
LEGIT_RE = re.compile(r"\*\*Legitimacy:\*\*\s*\**\s*([^\n*]+)", re.I)
ARCH_RE = re.compile(r"\*\*Archetype:\*\*\s*([^\n]+)", re.I)
URL_RE = re.compile(r"\*\*URL:\*\*\s*(?:URL:\s*)?(\S+)", re.I)
FENCE_RE = re.compile(r"## Machine Summary\s*```(?:yaml|yml)?\s*\n(.*?)```", re.S | re.I)
BLOCK_RE = re.compile(r"^#{1,3}\s*[A-G]\)", re.M)
NUM_RE = re.compile(r"^(\d+)-")
MIN_CHARS = 1500


def report_number(path) -> int | None:
    m = NUM_RE.match(Path(path).name)
    return int(m.group(1)) if m else None


def _list(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def parse(text: str) -> dict:
    """-> dict with ok (bool: looks like a real evaluation), problems (list), and the fields below (None if absent)."""
    out = {"ok": False, "problems": [], "score": None, "legitimacy": None, "archetype": None, "url": None,
           "company": None, "role": None, "final_decision": None, "hard_stops": [], "soft_gaps": [],
           "top_strengths": [], "risk_level": None, "confidence": None, "next_action": None,
           "advertised_comp": None, "work_auth": None, "blocks": len(set(BLOCK_RE.findall(text)))}
    ms = {}
    fm = FENCE_RE.search(text)
    if fm:
        try:
            ms = yaml.safe_load(fm.group(1)) or {}
            ms = ms if isinstance(ms, dict) else {}
        except yaml.YAMLError:
            out["problems"].append("machine summary is not valid YAML")
    else:
        out["problems"].append("no machine summary")
    score = ms.get("score")
    if score is None:
        m = SCORE_RE.search(text)
        score = m.group(1) if m else None
    try:
        out["score"] = round(float(str(score).split("/")[0]), 2) if score is not None else None
    except ValueError:
        out["score"] = None
    if out["score"] is None or not (0 < out["score"] <= 5):
        out["problems"].append("no usable score")
        out["score"] = None
    m = LEGIT_RE.search(text)
    out["legitimacy"] = (ms.get("legitimacy_tier") or (m.group(1).strip() if m else None)) or None
    m = ARCH_RE.search(text)
    out["archetype"] = ms.get("archetype") or (m.group(1).strip() if m else None)
    m = URL_RE.search(text)
    out["url"] = m.group(1) if m else None
    for k in ("company", "role", "final_decision", "risk_level", "confidence", "next_action", "advertised_comp", "work_auth"):
        out[k] = ms.get(k)
    for k in ("hard_stops", "soft_gaps", "top_strengths"):
        out[k] = _list(ms.get(k))
    if len(text) < MIN_CHARS:
        out["problems"].append(f"too short ({len(text)} chars)")
    if not fm and out["blocks"] < 3:
        out["problems"].append("no evaluation blocks (A-G)")
    out["ok"] = out["score"] is not None and len(text) >= MIN_CHARS and (bool(fm) or out["blocks"] >= 3)
    return out


def parse_file(path) -> dict:
    p = Path(path)
    r = parse(p.read_text(encoding="utf-8", errors="replace"))
    r["path"], r["number"] = str(p), report_number(p)
    return r
