"""Add company career pages to a profile's portals.yml (tracked_companies), preserving all its comments.

Only systems career-ops can scan automatically (see ingest_links.classify -> ats) are routable.
"""
import re

import yaml

from brain import profiles

ROUTABLE_ATS = {"greenhouse", "lever", "ashby", "workable", "recruitee", "workday", "smartrecruiters",
                "teamtailor", "breezy", "bamboohr", "personio", "jobvite", "icims"}


def _tracked(text: str) -> list[dict]:
    try:
        return (yaml.safe_load(text) or {}).get("tracked_companies") or []
    except yaml.YAMLError:
        return []


def add_companies(entries: list[dict], name: str | None = None) -> dict:
    """entries: [{name, careers_url, ats}]. Skips companies already tracked (same URL or same name).
    Returns {"added": [...], "duplicates": [...], "unsupported": [...]}."""
    name = name or profiles.get_active()
    if not name:
        raise RuntimeError("No active profile.")
    text = profiles.read_file(name, "portals.yml")
    if not text.strip():
        raise FileNotFoundError("This profile has no portals.yml yet - run: hire.py profile regenerate")
    existing = _tracked(text)
    urls = {(c.get("careers_url") or "").rstrip("/").lower() for c in existing}
    names = {(c.get("name") or "").strip().lower() for c in existing}
    res = {"added": [], "duplicates": [], "unsupported": []}
    block = ""
    for e in entries:
        url, nm, ats = e["careers_url"].rstrip("/"), (e.get("name") or "").strip(), e.get("ats")
        if ats not in ROUTABLE_ATS:
            res["unsupported"].append(url)
            continue
        if not nm:
            nm = re.sub(r"^https?://|\..*$", "", url).title()
        if url.lower() in urls or nm.lower() in names:
            res["duplicates"].append(url)
            continue
        urls.add(url.lower())
        names.add(nm.lower())
        block += f'  - name: {yaml.safe_dump(nm, allow_unicode=True).splitlines()[0]}\n' \
                 f'    careers_url: {url}\n    notes: "added from your sources"\n    enabled: true\n\n'
        res["added"].append(nm)
    if block:
        marker = "  # -- Added from your sources --\n\n"
        m = re.search(r"^tracked_companies:\n", text, re.M)
        if not m:
            raise RuntimeError("portals.yml has no tracked_companies section")
        if marker in text:
            at = text.index(marker) + len(marker)
            new = text[:at] + block + text[at:]
        else:
            new = text[: m.end()] + "\n" + marker + block + text[m.end():]
        profiles.write_file(name, "portals.yml", new)       # validates YAML + keeps a backup
    return res


def _block_re(url: str) -> "re.Pattern":
    """A tracked_companies list item whose careers_url equals `url` (comments/other items untouched)."""
    return re.compile(r"(^  - name:[^\n]*\n(?:    [^\n]*\n)*?    careers_url: " + re.escape(url.rstrip("/")) + r"/?[ \t]*\n(?:    [^\n]*\n)*\n?)", re.M)


def set_company_enabled(url: str, enabled: bool, name: str | None = None) -> bool:
    name = name or profiles.get_active()
    text = profiles.read_file(name, "portals.yml")
    m = _block_re(url).search(text)
    if not m:
        return False
    block = m.group(1)
    nb = re.sub(r"(^    enabled: )(true|false)", rf"\g<1>{'true' if enabled else 'false'}", block, flags=re.M)
    if nb == block and "    enabled:" not in block:
        nb = block.rstrip("\n") + f"\n    enabled: {'true' if enabled else 'false'}\n\n"
    if nb != block:
        profiles.write_file(name, "portals.yml", text.replace(block, nb, 1))
    return True


def remove_company(url: str, name: str | None = None) -> bool:
    name = name or profiles.get_active()
    text = profiles.read_file(name, "portals.yml")
    m = _block_re(url).search(text)
    if not m:
        return False
    profiles.write_file(name, "portals.yml", text.replace(m.group(1), "", 1))
    return True
