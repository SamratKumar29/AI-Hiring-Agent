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


def cmd_rank(a) -> int:
    from brain import rank

    try:
        r = rank.run(a.profile, max_n=a.max, retry_failed=a.retry_failed)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"\nRanked {r['ranked']}, failed {r['failed']}, still waiting {r['remaining']}"
          + ("  (stopped early: models unavailable - run again later)" if r["stopped_early"] else ""))
    if r["digest"]:
        print(f"Digest: {r['digest']}\nSee it with: ./venv/bin/python hire.py show")
    return 0 if (r["ranked"] or not r["failed"]) else 1


def cmd_show(a) -> int:
    import webbrowser

    from brain import digest

    try:
        items = digest.top(a.top, a.profile)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    if not items:
        print("Nothing ranked yet. Run: ./venv/bin/python hire.py discover  then  ./venv/bin/python hire.py rank")
        return 0
    for it in items:
        pay = it.get("advertised_comp") or it.get("salary_text") or "-"
        print(f"{it['rank']:>2}. {it['rank_score']:.1f}/5  [{it.get('chance', '?')} chance]  {it['company'] or '?'} - {it['title'] or '?'}")
        print(f"      {it.get('location') or '-'} | {pay} | {it['url']}")
        if it.get("why"):
            print(f"      why: {'; '.join(it['why'])}")
    if a.open:
        if 1 <= a.open <= len(items):
            print(f"Opening {items[a.open - 1]['url']}")
            webbrowser.open(items[a.open - 1]["url"])
        else:
            print(f"--open must be 1..{len(items)}")
            return 1
    return 0


SETUP_HELP = """
Telegram setup (3 minutes):
  1. In Telegram, open @BotFather and send  /newbot  (name it anything; the username must end in 'bot').
  2. BotFather replies with a token like 123456789:AAH...  Put it in brain/.env as  TELEGRAM_BOT_TOKEN=...
     (do not paste it into chats or commit it).
  3. Open your new bot in Telegram, press Start and send it:  hi
  4. Run this command again - it finds your chat id by itself and sends a test message.
"""


def cmd_notify(a) -> int:
    from brain import config, notify

    token = config.get("TELEGRAM_BOT_TOKEN")
    if a.action == "setup":
        if not token:
            print(SETUP_HELP)
            return 1
        chk = notify.check_token(token)
        if chk.get("network"):
            print(f"Could not reach Telegram (this is a network problem, not your token): {chk['detail'][:200]}\n"
                  "Check your internet/VPN/proxy settings and try again.")
            return 1
        if not chk["ok"]:
            print(f"The token in brain/.env was rejected: {chk['detail']}\n{SETUP_HELP}")
            return 1
        print(f"Token OK - bot @{chk['username']}")
        chat = config.get("TELEGRAM_CHAT_ID")
        if not chat:
            f = notify.find_chat_id(token)
            if not f["ok"]:
                print(f"{f['detail']}\n(Bot: https://t.me/{chk['username']})")
                return 1
            config.set_env_value("TELEGRAM_CHAT_ID", f["chat_id"])
            print(f"Found your chat ({f['name']}) and saved TELEGRAM_CHAT_ID to brain/.env")
        else:
            print("TELEGRAM_CHAT_ID already set.")
        a.action = "test"
    if a.action == "test":
        res = notify.send("AI Hiring Agent", "Test message: notifications work. Your daily job digest will arrive here.")
        for ch, r in res.items():
            print(f"{ch:<9}{'OK' if r['ok'] else ('skipped' if r.get('skipped') else 'FAILED')} - {r['detail']}")
        if not notify.delivered(res):
            print("Nothing was delivered. Run: ./venv/bin/python hire.py notify setup")
            return 1
        return 0
    return 0


def cmd_daily(a) -> int:
    from brain import daily

    try:
        r = daily.run(a.profile, max_evals=a.max, send=not a.no_send)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    return r["exit"]


RECORDED = ("discover", "rank", "daily", "tailor", "prep")      # shown in the UI run history


def cmd_ui(a) -> int:
    import subprocess
    import webbrowser

    from brain import config

    url = f"http://localhost:{a.port}"
    print(f"Starting the web interface at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        for opener in (["wslview", url], ["explorer.exe", url]):
            try:
                subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except OSError:
                continue
        else:
            webbrowser.open(url)
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(config.ROOT_DIR / "ui" / "app.py"),
                            "--server.address", "127.0.0.1", "--server.port", str(a.port), "--server.headless", "true",
                            "--browser.gatherUsageStats", "false"], cwd=config.ROOT_DIR)


def cmd_doctor(a) -> int:
    from brain import doctor

    res = doctor.run(llm=a.llm)
    mark = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}
    for r in res:
        print(f"[{mark[r['status']]}] {r['name']:<28} {r['detail']}")
        if r["fix"] and r["status"] != "PASS":
            print(f"       fix: {r['fix']}")
    s = doctor.summary(res)
    print(f"\n{s['PASS']} passed, {s['WARN']} warning(s), {s['FAIL']} failed" + ("" if a.llm else "   (add --llm to also test a real model call)"))
    return 1 if s["FAIL"] else 0


def cmd_schedule(a) -> int:
    from brain import config, schedule

    when = a.time or config.get("DAILY_TIME", "08:00")
    try:
        if a.action == "install":
            if a.windows:
                r = schedule.windows_install(when)
                print(f"Windows Task Scheduler: '{schedule.TASK_NAME}' daily at {r['time']}"
                      + ("; runs after a missed start" if r["catch_up"] else f"  (catch-up setting not applied: {r['detail']})"))
            else:
                r = schedule.cron_install(when)
                print(f"Installed in cron: {r['line']}")
                if schedule.cron_service_running() is False:
                    print("WARNING: the cron service is not running. Start it with: sudo service cron start")
                print("Note: cron only runs while WSL/this machine is awake. If it is often closed, also run:\n"
                      "  ./venv/bin/python hire.py schedule install --windows")
        elif a.action == "remove":
            a1 = schedule.cron_remove()
            a2 = schedule.windows_remove() if schedule.windows_available() else False
            print(("Removed cron entry. " if a1 else "No cron entry. ") + ("Removed Windows task." if a2 else "No Windows task."))
        else:
            c, w = schedule.cron_status(), schedule.windows_status()
            run = schedule.cron_service_running()
            print(f"cron:    {'ON  ' + c['detail'] if c['installed'] else 'off (' + c['detail'] + ')'}"
                  + ("" if run is None else f"   [service {'running' if run else 'NOT running'}]"))
            print(f"windows: {'ON' if w['installed'] else 'off'}")
            print(f"last run: {schedule.last_run() or 'never'}")
            print("Run now (same as the schedule): ./venv/bin/python hire.py daily")
    except (RuntimeError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def _job_or_exit(ref, profile):
    from brain import prep

    try:
        return prep.resolve(ref, profile)
    except prep.PrepError as e:
        print(f"ERROR: {e}")
        return None


def cmd_tailor(a) -> int:
    from brain import tailor

    job = _job_or_exit(a.job, a.profile)
    if not job:
        return 1
    print(f"Tailoring a CV for {job['company'] or '?'} - {job['title'] or '?'} with: {a.engine} (this can take a few minutes)")
    r = tailor.make_resume(job["job_id"], a.engine, a.profile)
    parts = r["results"].values() if a.engine == "both" else [r]
    for x in parts:
        print(f"  {x['engine']:<15}" + (f"OK  {x['pdf_path']}  (model {x.get('model') or '-'})" if x["ok"] else f"FAILED - {x['error']}"))
    if a.engine == "both" and r["ok"]:
        print("Open both PDFs and compare them before you apply.")
    return 0 if r["ok"] else 1


MENU = [("1", "cover", "Cover letter"), ("2", "interview", "Interview preparation"), ("3", "offer", "Offer / negotiation prep"),
        ("4", "followup", "Follow-up email"), ("5", "outreach", "Outreach messages (recruiter / hiring manager)"),
        ("6", "applied", "Mark as APPLIED (updates the tracker)")]


def cmd_prep(a) -> int:
    from brain import prep

    job = _job_or_exit(a.job, a.profile)
    if not job:
        return 1
    print(f"\n{job['company'] or '?'} - {job['title'] or '?'}\n{job['url']}")
    existing = prep.list_prep(job["job_id"], a.profile)

    def do(kind):
        if kind == "applied":
            r = prep.mark_applied(job["job_id"], a.profile)
            print(f"Marked as applied. Tracker sync: {r['sync']}")
            return True
        extra = ""
        if kind == "offer" and a.offer_file:
            extra = Path(a.offer_file).read_text(encoding="utf-8", errors="replace")
        r = prep.generate(job["job_id"], kind, a.profile, extra=extra)
        if not r["ok"]:
            print(f"  FAILED: {r['error']}")
            return False
        print(f"  saved: {r['path']}  (model {r['model']})")
        return True

    if a.kind:
        if a.kind not in prep.KINDS and a.kind != "applied":
            print(f"kind must be one of {list(prep.KINDS)} or applied")
            return 1
        return 0 if do(a.kind) else 1
    while True:
        print("\nWhat do you need?")
        for k, kind, label in MENU:
            mark = "  (exists)" if kind in existing else ""
            print(f"  {k}. {label}{mark}")
        print("  q. quit")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("q", "quit", ""):
            return 0
        pick = next((m for m in MENU if m[0] == choice), None)
        if not pick:
            print("Choose 1-6 or q.")
            continue
        if do(pick[1]) and pick[1] in prep.KINDS:
            existing = prep.list_prep(job["job_id"], a.profile)


def cmd_open(a) -> int:
    from brain import digest, prep

    try:
        items = digest.top(a.n, a.profile)
        if not 1 <= a.rank <= len(items):
            print(f"Rank {a.rank} not found. {len(items)} ranked job(s) - see: hire.py show")
            return 1
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    it = items[a.rank - 1]
    print(f"#{a.rank}  {it['company'] or '?'} - {it['title'] or '?'}   score {it['rank_score']:.1f}/5")
    print(f"Posting : {it['url']}")
    print(f"Report  : {it.get('report_path') or '(none)'}")
    print(f"Job id  : {it['job_id']}   (use with: hire.py tailor / prep)")
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
    k = sub.add_parser("rank", help="score queued jobs against your profile (uses the LLM)")
    k.add_argument("--max", type=int, default=None, help="most jobs to evaluate this run (default: MAX_EVALS_PER_RUN, 20)")
    k.add_argument("--retry-failed", action="store_true", help="try again jobs whose evaluation was unusable before")
    k.add_argument("--profile", help="profile name (default: active)")
    k.set_defaults(func=cmd_rank)
    w = sub.add_parser("show", help="show the best-ranked jobs")
    w.add_argument("--top", type=int, default=10)
    w.add_argument("--open", type=int, metavar="N", help="open job number N in your browser")
    w.add_argument("--profile", help="profile name (default: active)")
    w.set_defaults(func=cmd_show)
    n = sub.add_parser("notify", help="Telegram notifications: setup | test")
    n.add_argument("action", choices=["setup", "test"])
    n.set_defaults(func=cmd_notify)
    dl = sub.add_parser("daily", help="the full daily run: discover -> rank -> notify (what the schedule runs)")
    dl.add_argument("--max", type=int, help="most jobs to evaluate (default MAX_EVALS_PER_RUN)")
    dl.add_argument("--no-send", action="store_true", help="do everything but do not send notifications")
    dl.add_argument("--profile", help="profile name (default: active)")
    dl.set_defaults(func=cmd_daily)
    sc = sub.add_parser("schedule", help="install / remove / check the daily schedule")
    sc.add_argument("action", choices=["install", "remove", "status"])
    sc.add_argument("--time", help="HH:MM, 24-hour (default DAILY_TIME in brain/.env, 08:00)")
    sc.add_argument("--windows", action="store_true", help="use Windows Task Scheduler (runs after a missed start) instead of cron")
    sc.set_defaults(func=cmd_schedule)
    t = sub.add_parser("tailor", help="make a tailored CV PDF for a job")
    t.add_argument("job", help="report number (see 'show'), job id, or posting URL")
    t.add_argument("--engine", choices=["career-ops", "resume-matcher", "both"], default="career-ops")
    t.add_argument("--profile", help="profile name (default: active)")
    t.set_defaults(func=cmd_tailor)
    pr = sub.add_parser("prep", help="cover letter, interview prep, offer prep, follow-up, outreach for a job")
    pr.add_argument("job", help="report number (see 'show'), job id, or posting URL")
    pr.add_argument("--kind", help="skip the menu: cover | interview | offer | followup | outreach | applied")
    pr.add_argument("--offer-file", help="for --kind offer: a text file with the offer letter / contract")
    pr.add_argument("--profile", help="profile name (default: active)")
    pr.set_defaults(func=cmd_prep)
    op = sub.add_parser("open", help="show the posting URL and report path of ranked job number N")
    op.add_argument("rank", type=int)
    op.add_argument("--n", type=int, default=50, help="how many top jobs to consider")
    op.add_argument("--profile", help="profile name (default: active)")
    op.set_defaults(func=cmd_open)
    dc = sub.add_parser("doctor", help="check that everything is set up and working (PASS/WARN/FAIL list)")
    dc.add_argument("--llm", action="store_true", help="also make one real model call (slower, uses a little quota)")
    dc.set_defaults(func=cmd_doctor)
    ui = sub.add_parser("ui", help="open the web interface in your browser")
    ui.add_argument("--port", type=int, default=8501)
    ui.add_argument("--no-browser", action="store_true", help="do not try to open a browser window")
    ui.set_defaults(func=cmd_ui)
    a = ap.parse_args()
    if a.cmd in RECORDED:
        from brain import taskrunner
        with taskrunner.recording(a.cmd, getattr(a, "profile", None)):
            code = a.func(a)
            if code:
                taskrunner.set_exit(code)
        return 0
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
