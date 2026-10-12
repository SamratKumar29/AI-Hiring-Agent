#!/usr/bin/env python3
"""AI-Hiring-Agent orchestrator CLI.   python3 hire.py --help"""
import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_VENV_PY = _ROOT / "venv" / "bin" / "python"
sys.path.insert(0, str(_ROOT))
if _VENV_PY.exists() and sys.prefix == sys.base_prefix:
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

from brain import profiles  # noqa: E402


def cmd_profile(a) -> int:
    act = a.action
    if act == "list":
        names, active = profiles.list_profiles(), profiles.get_active()
        if not names:
            print("No profiles yet. Create one:  python3 hire.py profile create --resume <file>")
        for n in names:
            print(f"{'*' if n == active else ' '} {n}")
        return 0

    if act == "create":
        resume = a.resume or input("Path to your resume (.md/.pdf/.docx/.txt): ").strip()
        try:
            cv = profiles.read_resume(resume)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}")
            return 1
        name = a.name or input("Name for this profile (e.g. 'ai-engineer-india'): ").strip()
        try:
            profiles.slug(name)
            if profiles._dir(name).exists():
                print(f"ERROR: profile '{profiles.slug(name)}' already exists. Pick another name.")
                return 1
        except ValueError as e:
            print(f"ERROR: {e}")
            return 1
        if a.prefs_file:
            prefs = json.loads(Path(a.prefs_file).read_text())
        else:
            prefs = profiles.ask_preferences(cv)
        d = profiles.create_profile(name, resume, prefs)
        profiles.set_active(name)
        print(f"\nSaved profile '{profiles.slug(name)}' in {d} and made it ACTIVE.")
        print("Next: python3 hire.py profile activate")
        return 0

    if act == "trash":
        items = profiles.list_trash()
        for t in items:
            print(f"{t['trash_name']}   (profile '{t['profile']}', deleted {t['deleted_at']})")
        if not items:
            print("Trash is empty.")
        return 0

    if act == "restore":
        if not a.name:
            print("Use: profile restore <trash_name>   (see: profile trash)")
            return 1
        try:
            print(f"Restored as '{profiles.restore_profile(a.name, a.to)}'")
        except (FileNotFoundError, FileExistsError) as e:
            print(f"ERROR: {e}")
            return 1
        return 0

    if act in ("load", "show", "activate", "edit", "regenerate", "delete", "rename", "duplicate"):
        name = a.name or profiles.get_active()
        if not name:
            print("No profile selected. Use: python3 hire.py profile list")
            return 1
        try:
            p = profiles.load_profile(name)
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            return 1
        if act == "load":
            profiles.set_active(name)
            print(f"Active profile: {p['name']}")
        elif act == "show":
            print(json.dumps(p["prefs"], indent=2, ensure_ascii=False))
        elif act == "edit":
            changes = {}
            for kv in a.set or []:
                k, _, v = kv.partition("=")
                kind = next((f[3] for f in profiles.FIELDS if f[0] == k), "str")
                if kind == "salary":
                    changes[k], changes[k + "_text"] = profiles.parse_salary(v), v
                elif kind == "list":
                    changes[k] = profiles._to_list(v)
                elif kind == "bool":
                    changes[k] = profiles._to_bool(v)
                elif kind == "int":
                    changes[k] = int(v)
                else:
                    changes[k] = v
            profiles.update_preferences(name, changes)
            print(f"Updated {', '.join(changes) or 'nothing'} in '{p['name']}'. Run 'profile regenerate' to rebuild portals/profile.yml from the new answers")
        elif act == "regenerate":
            res = profiles.generate_files(name, use_llm=not a.no_llm)
            print(f"Regenerated {', '.join(res['written'])} for '{p['name']}' (old versions backed up). "
                  f"narrative from LLM: {res['narrative_generated']} | _profile.md from LLM: {res['profile_md_from_llm']}")
            print("Run 'profile activate' if this profile is not active yet.")
        elif act == "delete":
            if not a.yes:
                print(f"This moves '{p['name']}' (CV, settings, tracker, reports) to brain/data/trash/. Re-run with --yes to confirm.")
                return 1
            print(f"Deleted '{p['name']}' -> {profiles.delete_profile(name)}")
        elif act == "duplicate":
            if not a.to:
                print("Use: profile duplicate <name> --to <new>")
                return 1
            print(f"Created '{profiles.duplicate_profile(name, a.to)}' (settings and files copied; tracker/reports start empty)")
        elif act == "rename":
            if not a.to:
                print("Use: profile rename <old> --to <new>")
                return 1
            print(f"Renamed to '{profiles.rename_profile(name, a.to)}'")
        else:
            res = profiles.activate(name, use_llm=not a.no_llm)
            print(f"Activated '{res['profile']}'. All its files live in {res['dir']}")
            if res["written"]:
                print(f"  generated missing files: {', '.join(res['written'])}")
            for k, v in res["links"].items():
                print(f"  career-ops/{k:<14} -> {v}")
        return 0
    return 1


def cmd_sources(a) -> int:
    from brain import sources

    try:
        if a.action == "add":
            if not a.items:
                print("Use: sources add <url | file.pdf | file.txt | 'pasted text'> [more...]")
                return 1
            r = sources.add(a.items, name=a.profile, route=not a.no_route, force_type=a.type)
            for s in r["added"]:
                print(f"+ {s['id']}  {s['type']:<16} {(s['board'] or s['ats'] or '-'):<12} {s['url']}  -> {s['routed'] or ('DISABLED (unknown type - set it with: sources settype ' + s['id'] + ' <type>)' if not s['enabled'] else 'saved')}")
            for u in r["duplicates"]:
                print(f"= already saved: {u}")
            print(f"{r['found']} link(s) found, {len(r['added'])} added, {len(r['duplicates'])} already known.")
            if not r["found"]:
                print("No links found. Check the file or paste the URLs directly.")
            return 0
        if a.action == "preview":
            for c in sources.preview(a.items, name=a.profile):
                print(f"{c['type']:<16} {(c['board'] or c['ats'] or '-'):<12} {'(saved) ' if c['already_added'] else ''}{c['url']}")
            return 0
        if a.action == "list":
            rows = sources.list_sources(a.type, name=a.profile)
            for s in rows:
                print(f"{s['id']}  {'on ' if s['enabled'] else 'off'} {s['type']:<16} {(s['board'] or s['ats'] or '-'):<12} {s['url']}   [{s['routed']}]")
            print(f"{len(rows)} source(s).")
            return 0
        if a.action == "sync":
            print(sources.sync(name=a.profile))
            return 0
        if not a.items:
            print(f"Use: sources {a.action} <id>" + (" <type>" if a.action == "settype" else ""))
            return 1
        sid = a.items[0]
        if a.action == "remove":
            print(f"Removed {sources.remove(sid, name=a.profile)['url']}")
        elif a.action in ("enable", "disable"):
            s = sources.set_enabled(sid, a.action == "enable", name=a.profile)
            print(f"{a.action}d {s['url']}")
        elif a.action == "settype":
            s = sources.set_type(sid, a.items[1], name=a.profile)
            print(f"{s['url']} is now {s['type']} -> {s['routed'] or 'saved'}")
    except (KeyError, ValueError, RuntimeError, FileNotFoundError, IndexError) as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def cmd_discover(a) -> int:
    from brain import discover

    try:
        r = discover.run("manual" if a.manual else "scheduled", name=a.profile, scan_since_days=a.since)
    except (RuntimeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    print(f"\nDiscovery for '{r['profile']}' ({r['mode']}): {r['new_jobs']} new jobs found, {r['queued']} queued for ranking.")
    print(f"{'stage':<16}{'status':<9}detail")
    for name, s in r["stages"].items():
        print(f"{name:<16}{s['status']:<9}{s['detail'][:90]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="hire.py", description="AI Hiring Agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile", help="manage job-search profiles")
    p.add_argument("action", choices=["list", "create", "load", "show", "edit", "activate", "regenerate", "delete", "rename", "duplicate", "trash", "restore"])
    p.add_argument("name", nargs="?", help="profile name (default: active profile)")
    p.add_argument("--resume", help="resume file (.md/.pdf/.docx/.txt) for 'create'")
    p.add_argument("--prefs-file", help="JSON file with answers (skips the questionnaire)")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="for 'edit', e.g. --set min_base_salary='30 LPA'")
    p.add_argument("--no-llm", action="store_true", help="for 'activate'/'regenerate': skip LLM-written files")
    p.add_argument("--yes", action="store_true", help="confirm 'delete'")
    p.add_argument("--to", help="new name for rename / duplicate / restore")
    p.set_defaults(func=cmd_profile)
    q = sub.add_parser("sources", help="job boards / postings / company pages to search")
    q.add_argument("action", choices=["add", "preview", "list", "remove", "enable", "disable", "settype", "sync"])
    q.add_argument("items", nargs="*", help="URLs, files (.pdf .txt .md .csv .html .docx) or pasted text; or a source id")
    q.add_argument("--profile", help="profile name (default: active)")
    q.add_argument("--type", help="for list: filter; for add: force a type (single_posting|board_search|company_careers|unknown)")
    q.add_argument("--no-route", action="store_true", help="save only; do not put postings in the inbox / portals.yml yet")
    q.set_defaults(func=cmd_sources)
    d = sub.add_parser("discover", help="find new jobs (boards, scrapers, company pages) and queue them for ranking")
    d.add_argument("--manual", action="store_true", help="also run the LinkedIn job-scraper (slower, rate-limited)")
    d.add_argument("--scheduled", action="store_true", help="scheduled mode (default)")
    d.add_argument("--profile", help="profile name (default: active)")
    d.add_argument("--since", type=int, default=2, help="career-ops scan window in days (default 2)")
    d.set_defaults(func=cmd_discover)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
