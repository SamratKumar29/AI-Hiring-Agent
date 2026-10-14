import pandas as pd
import streamlit as st

from brain import config, digest, notify, profiles, schedule, taskrunner
from ui import common

st.header("Schedule & Notifications")
name = common.active_profile()

st.subheader("Daily run")
c = schedule.cron_status()
w = schedule.windows_status() if schedule.windows_available() else {"installed": False, "detail": "not available outside WSL"}
svc = schedule.cron_service_running()
a, b = st.columns(2)
a.metric("Linux/WSL cron", "ON" if c["installed"] else "off")
a.caption(c["detail"] + ("" if svc is None else f"  |  cron service {'running' if svc else 'NOT running (sudo service cron start)'}"))
b.metric("Windows Task Scheduler", "ON" if w["installed"] else "off")
b.caption(w["detail"][:150])
when = st.text_input("Daily time (HH:MM, 24-hour)", value=config.get("DAILY_TIME", "20:00"), key="sched_time")
x1, x2, x3 = st.columns(3)
try:
    schedule.parse_time(when)
    time_ok = True
except ValueError as e:
    st.error(str(e))
    time_ok = False
if x1.button("Install / update in cron", disabled=not time_ok, use_container_width=True):
    config.save_env({"DAILY_TIME": when})
    r = schedule.cron_install(when)
    st.success(f"Installed: {r['line']}")
    st.rerun()
if x2.button("Install on Windows too", disabled=not (time_ok and schedule.windows_available()), use_container_width=True,
             help="Also catches up after a missed start; works when WSL was closed."):
    config.save_env({"DAILY_TIME": when})
    r = schedule.windows_install(when)
    st.success(f"Windows task set for {r['time']}.")
    st.rerun()
if x3.button("Remove the schedule", use_container_width=True):
    schedule.cron_remove()
    if schedule.windows_available():
        schedule.windows_remove()
    st.rerun()
st.caption("Cron only runs while WSL/this computer is awake.")

st.subheader("Run now")
live = taskrunner.any_running(name)
send = st.checkbox("Send the result to Telegram/email", value=True, key="sched_send")
if st.button("Run the daily job now", disabled=bool(live), type="primary"):
    common.start_task("daily", ["daily"] + ([] if send else ["--no-send"]), name, "sched_run")
rid = st.session_state.get("sched_run") or (live["run_id"] if live else None)
if rid:
    common.show_run(rid, name, "sched")

st.subheader("Last 14 daily runs")
runs = taskrunner.list_runs("daily", 14, name)
if runs:
    st.dataframe(pd.DataFrame([{"": common.ICON.get(r["state"], ""), "started": common.ts(r["started"]), "took": common.duration(r),
                                "result": r["state"], "last line": r["last_line"][:100]} for r in runs]), use_container_width=True, hide_index=True)
else:
    st.caption("No daily runs recorded yet.")
lr = schedule.last_run()
if lr:
    st.caption(f"Last scheduled (cron) run: {lr}")

st.subheader("Digests")
ddir = profiles.workspace_path(name, "output") / "digests"
files = sorted(ddir.glob("*.md"), reverse=True) if ddir.exists() else []
if files:
    pick = st.selectbox("Open a digest", [f.name for f in files])
    st.markdown((ddir / pick).read_text(encoding="utf-8"))
else:
    st.caption("No digests yet.")

st.subheader("Notification channels")
tg = bool(config.get("TELEGRAM_BOT_TOKEN") and config.get("TELEGRAM_CHAT_ID"))
mail = all(config.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))
st.write(f"Telegram: {'✅ configured' if tg else '❌ not configured'}   |   Email: {'✅ configured' if mail else '➖ not configured'}")
if st.button("Send a test message to all channels"):
    res = notify.send("AI Hiring Agent test", "This is a test message.")
    for ch, r in res.items():
        if not r.get("skipped"):
            (st.success if r["ok"] else st.error)(f"{ch}: {r['detail']}")
    if not any(not r.get("skipped") for r in res.values()):
        st.warning("No channel is configured. Open Setup > Notifications.")
common.page_link("pages/1_Setup.py", "Edit notification settings", "⚙️")
