"""Profile manager: resume + preferences -> saved profile -> career-ops files.

ALL profile files live in ONE place:  career-ops/profile/<slug>/
    preferences.json  cv.md  profile.yml  portals.yml  _profile.md
    workspace/{data,reports,output}     <- per-profile job tracker, evaluation reports, generated PDFs
career-ops hard-codes where it reads these, so activate() SYMLINKS the active profile's files into
career-ops/{cv.md, config/profile.yml, portals.yml, modes/_profile.md, data, reports, output}.
Switching profiles = re-pointing the links (nothing is copied, nothing is lost).
Active profile name: brain/data/state.json.  Deleted profiles go to brain/data/trash/ (recoverable).
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from brain import config

CAREER_OPS = config.ROOT_DIR / "career-ops"
PROFILES_DIR = CAREER_OPS / "profile"
LEGACY_PROFILES_DIR = config.ROOT_DIR / "profiles"      # v1 location, auto-migrated
STATE_FILE = config.DATA_DIR / "state.json"
EDITABLE_FILES = ("cv.md", "profile.yml", "portals.yml", "_profile.md")
WORKSPACE_DIRS = ("data", "reports", "output")

SENIORITY_WORDS = {"senior", "sr", "sr.", "staff", "principal", "lead", "junior", "jr", "jr.",
                   "head", "associate", "mid", "entry", "level", "i", "ii", "iii"}
REMOTE_FEEDS = ["RemoteOK:remoteok", "Remotive:remotive", "We Work Remotely:weworkremotely",
                "Himalayas:himalayas", "Working Nomads:workingnomads", "Jobicy:jobicy"]


def form_to_prefs(raw: dict) -> tuple[dict, list[str]]:
    """Web-form answers (all strings/lists/bools) -> (preferences, problems). Same rules as the questionnaire."""
    prefs, problems = {}, []
    for key, prompt, default, kind in FIELDS:
        v = raw.get(key, default)
        txt = ", ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v)).strip()
        label = prompt.split(" (")[0].split(":")[0]
        if kind == "list":
            prefs[key] = _to_list(txt)
        elif kind == "salary":
            if txt and parse_salary(txt) is None:
                problems.append(f"{label}: could not read '{txt}' - try '25 LPA' or '120k'.")
            prefs[key] = parse_salary(txt) if txt else None
            prefs[key + "_text"] = txt
        elif kind == "int":
            if txt and not re.fullmatch(r"\d+(\.\d+)?", txt):
                problems.append(f"{label}: please enter a number.")
                txt = ""
            prefs[key] = float(txt) if "." in txt else int(txt or 0)
        elif kind == "bool":
            prefs[key] = v if isinstance(v, bool) else _to_bool(txt)
        elif kind == "mode":
            if txt.lower() not in ("remote", "hybrid", "onsite", "any"):
                problems.append(f"{label}: choose remote, hybrid, onsite or any.")
                txt = "any"
            prefs[key] = txt.lower()
        else:
            prefs[key] = txt
    if not prefs.get("target_roles"):
        problems.append("Target job titles: enter at least one.")
    return prefs, problems


# ---------------------------------------------------------------- helpers
def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not s:
        raise ValueError("Profile name must contain letters or digits")
    return s


def parse_salary(text) -> int | None:
    """'30 LPA' -> 3000000, '120k' -> 120000, '1.5m' -> 1500000, '30-40 LPA' -> 3000000 (min)."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    t = str(text).lower().replace(",", "")
    unit = r"(lpa|lakhs?|lacs?|crores?|cr|l\b|k|m)?"
    m = re.search(rf"(\d+(?:\.\d+)?)\s*{unit}(?:\s*(?:-|to|–)\s*\$?\d+(?:\.\d+)?\s*{unit})?", t)
    if not m:
        return None
    unit_used = m.group(2) or m.group(3) or ""   # '30-40 LPA': the unit follows the second number
    mult = {"lpa": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "k": 1e3,
            "m": 1e6, "cr": 1e7, "crore": 1e7, "crores": 1e7}.get(unit_used, 1)
    return int(float(m.group(1)) * mult)


def format_money(amount, currency: str) -> str:
    if not amount:
        return ""
    if currency.upper() == "INR" and amount >= 1e5:
        return f"INR {amount / 1e5:g} LPA"
    return f"{currency.upper()} {amount:,.0f}"


def read_resume(path) -> str:
    """Return resume text as markdown/plain text. Supports .md .txt .pdf .docx"""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Resume not found: {p}")
    ext = p.suffix.lower()
    if ext in (".md", ".txt", ".markdown"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        from pypdf import PdfReader

        text = "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages).strip()
        if not text:
            raise ValueError("PDF has no extractable text (scanned?). Convert it to .md/.docx first.")
        return text
    if ext == ".docx":
        import docx

        d = docx.Document(str(p))
        parts = [para.text for para in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(x for x in parts if x.strip())
    raise ValueError(f"Unsupported resume type '{ext}'. Use .md, .txt, .pdf or .docx")


def guess_identity(cv: str) -> dict:
    """Best-effort contact details from CV text (user confirms them in the questionnaire)."""
    out = {}
    m = re.search(r"^#\s+(.+)$", cv, re.M)
    if m:
        name = re.split(r"\s+[—–|-]\s+", m.group(1).strip())[0]
        out["full_name"] = name.strip()
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", cv)
    if m:
        out["email"] = m.group(0)
    m = re.search(r"(\+?\d[\d\s().-]{8,}\d)", cv)
    if m:
        out["phone"] = m.group(1).strip()
    m = re.search(r"(?:https?://)?(?:www\.)?(linkedin\.com/in/[\w%-]+)", cv)
    if m:
        out["linkedin"] = m.group(1)
    m = re.search(r"(?:https?://)?(?:www\.)?(github\.com/[\w-]+)", cv)
    if m:
        out["github"] = m.group(1)
    return out


# ------------------------------------------------------------ questionnaire
def _to_list(v):
    if isinstance(v, list):
        return [x.strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _to_bool(v):
    return str(v).strip().lower() in ("y", "yes", "true", "1")


# key, prompt, default, kind
FIELDS = [
    ("full_name", "Full name", "", "str"),
    ("email", "Email", "", "str"),
    ("phone", "Phone", "", "str"),
    ("linkedin", "LinkedIn (e.g. linkedin.com/in/you)", "", "str"),
    ("github", "GitHub (e.g. github.com/you)", "", "str"),
    ("city", "Current city", "", "str"),
    ("country", "Current country", "India", "str"),
    ("target_roles", "Target job titles (comma separated, best first)", "AI Engineer, ML Engineer", "list"),
    ("locations", "Preferred job locations (comma separated, e.g. Bengaluru, Remote)", "Remote", "list"),
    ("work_mode", "Work mode: remote / hybrid / onsite / any", "any", "mode"),
    ("currency", "Salary currency code (INR, USD, EUR...)", "INR", "str"),
    ("min_base_salary", "MINIMUM base salary per year (e.g. 25 LPA, 120k) - jobs below this are dropped",
     "", "salary"),
    ("preferred_salary", "Preferred/target salary per year", "", "salary"),
    ("years_experience", "Years of professional experience", "0", "int"),
    ("must_have_skills", "Must-have skills (comma separated)", "", "list"),
    ("exclude", "Deal-breakers: companies / industries / keywords to avoid (comma separated)", "", "list"),
    ("visa_status", "Work authorization / visa status", "No sponsorship needed", "str"),
    ("needs_sponsorship", "Need visa sponsorship for other countries? (y/n)", "n", "bool"),
    ("notice_period_days", "Notice period in days", "30", "int"),
    ("languages", "Languages (comma separated)", "English", "list"),
]


def ask_preferences(cv_text: str = "", input_fn=input, output_fn=print, defaults: dict | None = None) -> dict:
    """Interactive questionnaire. Enter accepts the shown default; EOF accepts defaults."""
    guessed = {**guess_identity(cv_text), **(defaults or {})}
    prefs: dict = {}
    output_fn("\nAnswer a few questions (press Enter to accept the [default]).\n")
    for key, prompt, default, kind in FIELDS:
        dflt = guessed.get(key, default)
        if isinstance(dflt, list):
            dflt = ", ".join(dflt)
        if dflt not in ("", None) and kind == "salary" and not isinstance(dflt, str):
            dflt = str(dflt)
        for _ in range(3):
            try:
                raw = input_fn(f"{prompt} [{dflt}]: ").strip()
            except EOFError:
                raw = ""
            raw = raw or str(dflt or "")
            if kind == "salary" and raw and parse_salary(raw) is None:
                output_fn("  Could not read that amount, try e.g. '25 LPA' or '120k'.")
                continue
            if kind == "mode" and raw.lower() not in ("remote", "hybrid", "onsite", "any"):
                output_fn("  Please type remote, hybrid, onsite or any.")
                continue
            if kind == "int" and raw and not re.fullmatch(r"\d+(\.\d+)?", raw):
                output_fn("  Please type a number.")
                continue
            break
        else:
            raw = str(default or "")
        if kind == "list":
            prefs[key] = _to_list(raw)
        elif kind == "salary":
            prefs[key] = parse_salary(raw)
            prefs[key + "_text"] = raw
        elif kind == "int":
            prefs[key] = float(raw) if "." in raw else int(raw or 0)
        elif kind == "bool":
            prefs[key] = _to_bool(raw)
        elif kind == "mode":
            prefs[key] = raw.lower()
        else:
            prefs[key] = raw
    if not prefs.get("min_base_salary"):
        output_fn("\nNOTE: no minimum salary set - salary filtering will be skipped until you add one "
                  "(hire.py profile edit).")
    return prefs


# ------------------------------------------------------------ storage
def _dir(name: str) -> Path:
    return PROFILES_DIR / slug(name)


def _link_map() -> dict:
    """profile file name -> where career-ops reads it."""
    return {"cv.md": CAREER_OPS / "cv.md", "profile.yml": CAREER_OPS / "config" / "profile.yml",
            "portals.yml": CAREER_OPS / "portals.yml", "_profile.md": CAREER_OPS / "modes" / "_profile.md"}


def migrate_legacy() -> list[str]:
    """Move v1 profiles/<slug> (repo root) into career-ops/profile/<slug>. Idempotent."""
    moved = []
    if LEGACY_PROFILES_DIR.exists() and LEGACY_PROFILES_DIR.resolve() != PROFILES_DIR.resolve():
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        for d in LEGACY_PROFILES_DIR.iterdir():
            if d.is_dir() and (d / "preferences.json").exists() and not (PROFILES_DIR / d.name).exists():
                shutil.move(str(d), str(PROFILES_DIR / d.name))
                moved.append(d.name)
        try:
            LEGACY_PROFILES_DIR.rmdir()
        except OSError:
            pass
    return moved


def list_profiles() -> list[str]:
    migrate_legacy()
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.name for p in PROFILES_DIR.iterdir() if (p / "preferences.json").exists())


def create_profile(name: str, resume_path, prefs: dict, overwrite: bool = False) -> Path:
    migrate_legacy()
    d = _dir(name)
    if d.exists() and not overwrite:
        raise FileExistsError(f"Profile '{slug(name)}' already exists (use a different name or overwrite).")
    cv = read_resume(resume_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "cv.md").write_text(cv, encoding="utf-8")
    data = {"profile_name": slug(name), "created": time.strftime("%Y-%m-%d"), **prefs}
    (d / "preferences.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _ensure_workspace(d)
    return d


def load_profile(name: str) -> dict:
    migrate_legacy()
    d = _dir(name)
    if not (d / "preferences.json").exists():
        raise FileNotFoundError(f"No profile '{slug(name)}'. Existing: {', '.join(list_profiles()) or 'none'}")
    files = {f: (d / f).exists() for f in EDITABLE_FILES}
    return {"name": slug(name), "dir": d, "cv": (d / "cv.md").read_text(encoding="utf-8"),
            "prefs": json.loads((d / "preferences.json").read_text(encoding="utf-8")), "files": files}


def update_preferences(name: str, changes: dict) -> dict:
    p = load_profile(name)
    prefs = {**p["prefs"], **changes}
    (p["dir"] / "preferences.json").write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")
    return prefs


def read_file(name: str, fname: str) -> str:
    if fname not in EDITABLE_FILES:
        raise ValueError(f"Not an editable profile file: {fname}")
    f = _dir(name) / fname
    return f.read_text(encoding="utf-8") if f.exists() else ""


def write_file(name: str, fname: str, text: str) -> None:
    """Edit a profile file (UI/CLI). YAML files are validated first so a typo can't break career-ops."""
    if fname not in EDITABLE_FILES:
        raise ValueError(f"Not an editable profile file: {fname}")
    if fname.endswith(".yml"):
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML, not saved: {e}") from None
    load_profile(name)  # must exist
    f = _dir(name) / fname
    _backup(f, f"{slug(name)}-{fname}")
    f.write_text(text, encoding="utf-8")


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=2))


def get_active() -> str | None:
    n = _state().get("active_profile")
    return n if n in list_profiles() else None


def set_active(name: str) -> None:
    load_profile(name)  # validates
    st = _state()
    st["active_profile"] = slug(name)
    _save_state(st)


def _ensure_workspace(d: Path) -> None:
    for w in WORKSPACE_DIRS:
        (d / "workspace" / w).mkdir(parents=True, exist_ok=True)


def _is_empty_dir(p: Path) -> bool:
    return not any(x for x in p.iterdir() if x.name != ".gitkeep")


def _place_link(link: Path, dest: Path, tag: str) -> str:
    """Make `link` a symlink to `dest`. A real file/dir already at `link` is adopted into the profile
    if the profile has no copy yet, otherwise backed up to brain/data/backups/. Returns what happened."""
    link.parent.mkdir(parents=True, exist_ok=True)
    action = "linked"
    if link.is_symlink():
        if os.path.realpath(link) == os.path.realpath(dest):
            return "unchanged"
        link.unlink()
    elif link.exists():
        if dest.is_dir():
            if not _is_empty_dir(link) and _is_empty_dir(dest):      # adopt existing work
                for x in link.iterdir():
                    if x.name != ".gitkeep":
                        shutil.move(str(x), str(dest / x.name))
                action = "adopted"
            elif not _is_empty_dir(link):
                bk = config.DATA_DIR / "backups" / time.strftime("%Y%m%d-%H%M%S") / tag
                bk.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(link), str(bk))
                action = "backed-up"
            if link.exists() and not link.is_symlink():
                shutil.rmtree(link)
        else:
            if not dest.exists():                                    # adopt generated file
                shutil.move(str(link), str(dest))
                action = "adopted"
            else:
                if link.read_bytes() != dest.read_bytes():
                    _backup(link, tag)
                link.unlink()
    link.symlink_to(dest)
    return action


def _hide_tracked_placeholders() -> None:
    """data/ reports/ output/ become symlinks; tell git to ignore their tracked .gitkeep files (best effort)."""
    try:
        subprocess.run(["git", "-C", str(CAREER_OPS), "update-index", "--skip-worktree",
                        *[f"{w}/.gitkeep" for w in WORKSPACE_DIRS]],
                       capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def link_active(name: str) -> dict:
    """Point career-ops at this profile's files + workspace."""
    d = _dir(name)
    _ensure_workspace(d)
    res = {}
    for fname, link in _link_map().items():
        if (d / fname).exists() or (link.exists() and not link.is_symlink()):
            if not (d / fname).exists():
                (d / fname).touch()
            res[fname] = _place_link(link, d / fname, f"{slug(name)}-{fname}")
    for w in WORKSPACE_DIRS:
        res[w + "/"] = _place_link(CAREER_OPS / w, d / "workspace" / w, f"{slug(name)}-{w}")
    _hide_tracked_placeholders()
    return res


def unlink_all() -> None:
    for link in [*_link_map().values(), *(CAREER_OPS / w for w in WORKSPACE_DIRS)]:
        if link.is_symlink():
            link.unlink()


def delete_profile(name: str) -> Path:
    """Soft delete: moves the profile (incl. its tracker/reports) to brain/data/trash/ so it is recoverable."""
    p = load_profile(name)
    if get_active() == p["name"]:
        unlink_all()
        st = _state()
        st.pop("active_profile", None)
        _save_state(st)
    dest = config.DATA_DIR / "trash" / f"{time.strftime('%Y%m%d-%H%M%S')}-{p['name']}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p["dir"]), str(dest))
    return dest


def workspace_path(name: str | None = None, sub: str = "data") -> Path:
    """Folder inside a profile's workspace (data | reports | output). Defaults to the ACTIVE profile."""
    if sub not in WORKSPACE_DIRS:
        raise ValueError(f"sub must be one of {WORKSPACE_DIRS}")
    name = name or get_active()
    if not name:
        raise RuntimeError("No active profile. Create one (hire.py profile create) or activate one first.")
    d = _dir(name)
    if not (d / "preferences.json").exists():
        raise FileNotFoundError(f"No profile '{slug(name)}'")
    path = d / "workspace" / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def duplicate_profile(src: str, new: str) -> str:
    """Copy settings + files (NOT the job tracker/reports) into a new profile."""
    p = load_profile(src)
    nd = _dir(new)
    if nd.exists():
        raise FileExistsError(f"Profile '{slug(new)}' already exists.")
    nd.mkdir(parents=True)
    for f in (*EDITABLE_FILES, "preferences.json", "sources.json"):
        if (p["dir"] / f).exists():
            shutil.copy2(p["dir"] / f, nd / f)
    prefs = json.loads((nd / "preferences.json").read_text())
    prefs.update(profile_name=slug(new), created=time.strftime("%Y-%m-%d"))
    (nd / "preferences.json").write_text(json.dumps(prefs, indent=2, ensure_ascii=False))
    _ensure_workspace(nd)
    return slug(new)


def list_trash() -> list[dict]:
    """Deleted profiles that can be restored, newest first."""
    root = config.DATA_DIR / "trash"
    out = []
    if root.exists():
        for d in sorted(root.iterdir(), reverse=True):
            if (d / "preferences.json").exists():
                stamp, _, prof = d.name.partition("-")  # YYYYMMDD
                m = re.match(r"(\d{8}-\d{6})-(.+)", d.name)
                out.append({"trash_name": d.name, "profile": m.group(2) if m else prof,
                            "deleted_at": m.group(1) if m else "", "path": str(d)})
    return out


def restore_profile(trash_name: str, new_name: str | None = None) -> str:
    src = config.DATA_DIR / "trash" / trash_name
    if not (src / "preferences.json").exists():
        raise FileNotFoundError(f"Nothing in trash called '{trash_name}'")
    m = re.match(r"\d{8}-\d{6}-(.+)", trash_name)
    target = slug(new_name or (m.group(1) if m else trash_name))
    if _dir(target).exists():
        raise FileExistsError(f"Profile '{target}' already exists - restore under another name.")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(_dir(target)))
    prefs = json.loads((_dir(target) / "preferences.json").read_text())
    prefs["profile_name"] = target
    (_dir(target) / "preferences.json").write_text(json.dumps(prefs, indent=2, ensure_ascii=False))
    return target


def rename_profile(old: str, new: str) -> str:
    p = load_profile(old)
    nd = _dir(new)
    if nd.exists():
        raise FileExistsError(f"Profile '{slug(new)}' already exists.")
    was_active = get_active() == p["name"]
    if was_active:
        unlink_all()
    shutil.move(str(p["dir"]), str(nd))
    prefs = json.loads((nd / "preferences.json").read_text())
    prefs["profile_name"] = slug(new)
    (nd / "preferences.json").write_text(json.dumps(prefs, indent=2, ensure_ascii=False))
    if was_active:
        _save_state({**_state(), "active_profile": slug(new)})
        link_active(new)
    return slug(new)


# ------------------------------------------------------------ career-ops rendering
def core_titles(roles: list[str]) -> list[str]:
    """'Senior AI Engineer' -> 'AI Engineer' (strip seniority so title matching is broader)."""
    out, seen = [], set()
    for r in roles:
        words = [w for w in r.split() if w.lower().strip(",") not in SENIORITY_WORDS]
        core = " ".join(words).strip()
        if core and core.lower() not in seen:
            seen.add(core.lower())
            out.append(core)
    return out


def render_profile_yml(prefs: dict, narrative: dict | None = None) -> str:
    base = yaml.safe_load((CAREER_OPS / "config" / "profile.example.yml").read_text(encoding="utf-8"))
    cur = prefs.get("currency", "USD")
    nar = narrative or {}
    roles = prefs.get("target_roles") or []
    base["candidate"].update({
        "full_name": prefs.get("full_name", ""), "email": prefs.get("email", ""),
        "phone": prefs.get("phone", ""), "location": ", ".join(x for x in (prefs.get("city"), prefs.get("country")) if x),
        "linkedin": prefs.get("linkedin", ""), "github": prefs.get("github", ""),
        "portfolio_url": "", "twitter": "",
    })
    base["target_roles"] = {
        "primary": roles,
        "archetypes": [{"name": r, "level": "Any", "fit": "primary" if i == 0 else "secondary"}
                       for i, r in enumerate(roles)],
    }
    base["narrative"] = {"headline": nar.get("headline", ""), "exit_story": nar.get("exit_story", ""),
                         "superpowers": nar.get("superpowers", []), "proof_points": []}
    base["compensation"] = {
        "target_range": format_money(prefs.get("preferred_salary") or prefs.get("min_base_salary"), cur),
        "currency": cur,
        "minimum": format_money(prefs.get("min_base_salary"), cur),
        "location_flexibility": f"Work mode: {prefs.get('work_mode', 'any')}; locations: "
                                f"{', '.join(prefs.get('locations', []))}",
    }
    base["location"] = {
        "country": prefs.get("country", ""), "city": prefs.get("city", ""), "timezone": "",
        "visa_status": prefs.get("visa_status", ""), "authorized_in": [prefs.get("country", "")],
        "needs_sponsorship": bool(prefs.get("needs_sponsorship")),
    }
    base["cover_letter"] = {"notice_period_days": prefs.get("notice_period_days", 30),
                            "primary_domain": ", ".join(roles[:1])}
    return "# Generated by AI-Hiring-Agent from profiles/<name>/preferences.json - edit the profile, then re-activate.\n" \
        + yaml.safe_dump(base, sort_keys=False, allow_unicode=True)


def render_portals(prefs: dict) -> str:
    text = (CAREER_OPS / "templates" / "portals.example.yml").read_text(encoding="utf-8")
    positives = core_titles(prefs.get("target_roles") or []) or ["Engineer"]
    # 1) title_filter.positive
    pos_block = "  positive:\n" + "".join(f'    - "{p}"\n' for p in positives)
    text, n = re.subn(r"^  positive:\n(?:(?:    .*|\s*)\n)*?(?=^  negative:)", pos_block, text, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError("portals template changed: could not find title_filter.positive block")
    # 2) extra negatives (deal-breakers)
    extra = "".join(f'    - "{x}"\n' for x in prefs.get("exclude") or [])
    if extra:
        text = re.sub(r"^  negative:\n", lambda m: m.group(0) + "    # deal-breakers from your profile\n" + extra,
                      text, count=1, flags=re.M)
    # 3) location_filter
    locs = prefs.get("locations") or []
    mode = prefs.get("work_mode", "any")
    allow = list(locs)
    if mode in ("remote", "hybrid", "any") and "remote" not in [x.lower() for x in allow]:
        allow.append("Remote")
    if allow:
        loc = "location_filter:\n  always_allow:\n" + "".join(f'    - "{x}"\n' for x in locs) \
              + "  allow:\n" + "".join(f'    - "{x}"\n' for x in allow) + "\n"
        text = text.replace("# -- Title filter --", loc + "# -- Title filter --", 1)
    # 4) remote feeds (no extra fields needed)
    if mode in ("remote", "hybrid", "any"):
        feeds = "".join(f"  - name: {n}\n    provider: {p}\n    enabled: true\n\n"
                        for n, p in (f.split(":") for f in REMOTE_FEEDS))
        text = re.sub(r"^tracked_companies:\n", lambda m: m.group(0) + "\n  # -- Remote feeds (added by profile) --\n\n"
                      + feeds, text, count=1, flags=re.M)
    return text


NARRATIVE_PROMPT = """From the CV below, write JSON with exactly these keys:
"headline" (one line professional headline), "exit_story" (2 sentences: background and what the candidate wants next),
"superpowers" (list of 3-5 short strengths). Use ONLY facts in the CV. Output JSON only, no markdown fences.

TARGET ROLES: {roles}

CV:
{cv}"""


def generate_narrative(cv: str, prefs: dict, chat_fn=None) -> dict:
    """LLM-written headline/exit story. Falls back to {} (left blank) if the LLM is unavailable."""
    try:
        if chat_fn is None:
            from brain import llm
            chat_fn = lambda p: llm.chat([{"role": "user", "content": p}], max_tokens=3000, timeout=120)[0]  # noqa: E731
        raw = chat_fn(NARRATIVE_PROMPT.format(roles=", ".join(prefs.get("target_roles", [])), cv=cv[:12000]))
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0))
        return {"headline": str(data.get("headline", "")), "exit_story": str(data.get("exit_story", "")),
                "superpowers": [str(x) for x in data.get("superpowers", [])][:5]}
    except Exception:  # noqa: BLE001
        return {}


PROFILE_MD_PROMPT = """You are customizing a career-ops file. Below is the TEMPLATE (modes/_profile.md) and the candidate's
CV and preferences. Output the COMPLETE customized file in markdown: keep every section heading of the template,
but replace the example archetypes, framing, narrative and proof points with ones based ONLY on facts in the CV.
Never invent employers, titles, dates or metrics. Keep the 'Your Location Policy' consistent with the preferences.
Output the markdown file only (no code fences, no commentary).

PREFERENCES (JSON):
{prefs}

CV:
{cv}

TEMPLATE:
{template}"""


def render_profile_md(cv: str, prefs: dict, chat_fn=None) -> tuple[str, bool]:
    """Return (markdown, used_llm). Falls back to template + deterministic preference section."""
    template = (CAREER_OPS / "modes" / "_profile.template.md").read_text(encoding="utf-8")
    try:
        if chat_fn is None:
            from brain import llm
            chat_fn = lambda p: llm.chat([{"role": "user", "content": p}], max_tokens=6000, timeout=180)[0]  # noqa: E731
        out = chat_fn(PROFILE_MD_PROMPT.format(prefs=json.dumps(prefs, ensure_ascii=False), cv=cv[:12000],
                                               template=template)).strip()
        out = re.sub(r"^```(?:markdown)?\n|\n```$", "", out)
        if "## Your Target Roles" in out and "## Your Exit Narrative" in out:
            return out + "\n", True
    except Exception:  # noqa: BLE001
        pass
    roles = "\n".join(f"- {r}" for r in prefs.get("target_roles", []))
    extra = (f"\n\n## Candidate Preferences (auto-generated)\n\n### Target roles\n{roles}\n\n"
             f"- Work mode: {prefs.get('work_mode')}\n- Locations: {', '.join(prefs.get('locations', []))}\n"
             f"- Minimum base salary: {format_money(prefs.get('min_base_salary'), prefs.get('currency', ''))}\n"
             f"- Must-have skills: {', '.join(prefs.get('must_have_skills', []))}\n"
             f"- Deal-breakers: {', '.join(prefs.get('exclude', []))}\n")
    return template + extra, False


def _backup(path: Path, tag: str) -> None:
    if path.exists() and not path.is_symlink():
        dest = config.DATA_DIR / "backups" / time.strftime("%Y%m%d-%H%M%S") / tag
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def generate_files(name: str, use_llm: bool = True, chat_fn=None, only: tuple | None = None) -> dict:
    """(Re)generate profile.yml, portals.yml, _profile.md from the saved preferences + CV.
    Overwrites those files (old versions are backed up). cv.md is never touched."""
    p = load_profile(name)
    prefs, cv, d = p["prefs"], p["cv"], p["dir"]
    want = only or ("profile.yml", "portals.yml", "_profile.md")
    for f in want:
        _backup(d / f, f"{p['name']}-{f}")
    out = {"narrative_generated": False, "profile_md_from_llm": False, "written": []}
    if "profile.yml" in want:
        narrative = generate_narrative(cv, prefs, chat_fn) if use_llm else {}
        (d / "profile.yml").write_text(render_profile_yml(prefs, narrative), encoding="utf-8")
        out["narrative_generated"] = bool(narrative)
        out["written"].append("profile.yml")
    if "portals.yml" in want:
        (d / "portals.yml").write_text(render_portals(prefs), encoding="utf-8")
        out["written"].append("portals.yml")
    if "_profile.md" in want:
        pmd, used = render_profile_md(cv, prefs, chat_fn) if use_llm else render_profile_md(cv, prefs, lambda _: "")
        (d / "_profile.md").write_text(pmd, encoding="utf-8")
        out["profile_md_from_llm"] = used
        out["written"].append("_profile.md")
    return out


def activate(name: str, use_llm: bool = True, chat_fn=None) -> dict:
    """Make `name` the active profile: generate any MISSING files, then link it into career-ops.
    Existing (possibly hand-edited) files are never overwritten - use generate_files() for that."""
    p = load_profile(name)
    d = p["dir"]
    # adopt files generated by an older version into the profile before deciding what is missing
    for fname, link in _link_map().items():
        if not (d / fname).exists() and link.exists() and not link.is_symlink():
            shutil.move(str(link), str(d / fname))
    missing = tuple(f for f in ("profile.yml", "portals.yml", "_profile.md") if not (d / f).exists())
    gen = generate_files(name, use_llm, chat_fn, only=missing) if missing else \
        {"narrative_generated": False, "profile_md_from_llm": False, "written": []}
    links = link_active(name)
    set_active(name)
    return {"profile": p["name"], **gen, "links": links, "dir": str(d)}
