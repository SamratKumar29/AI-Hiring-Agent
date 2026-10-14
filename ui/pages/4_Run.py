import pandas as pd
import streamlit as st

from brain import budget, taskrunner
from ui import common

st.header("Run")
name = common.active_profile()
common.llm_banner()
live = taskrunner.any_running(name)
if live:
    st.info(f"A {live['kind']} run is in progress. Wait for it to finish or cancel it below.")

c1, c2, c3, c4 = st.columns(4)
if c1.button("🔎 Discover (manual: all scrapers incl. LinkedIn)", disabled=bool(live), use_container_width=True):
    common.start_task("discover", ["discover", "--manual"], name, "run_id")
if c2.button("🔎 Discover (scheduled set)", disabled=bool(live), use_container_width=True):
    common.start_task("discover", ["discover", "--scheduled"], name, "run_id")
maxn = st.slider("Most jobs to rank in one run", 1, 100, budget.max_evals(), help="Each evaluation uses AI credits / time.")
if c3.button("🧮 Rank new jobs", disabled=bool(live), use_container_width=True):
    common.start_task("rank", ["rank", "--max", str(maxn)], name, "run_id")
send = st.checkbox("Send the result to Telegram/email at the end of a full daily run", value=False)
if c4.button("🚀 Full daily run", disabled=bool(live), use_container_width=True):
    common.start_task("daily", ["daily", "--max", str(maxn)] + ([] if send else ["--no-send"]), name, "run_id")

rid = st.session_state.get("run_id") or (live["run_id"] if live else None)
if rid:
    st.subheader("Progress")
    common.show_run(rid, name, "run")

st.subheader("History")
runs = taskrunner.list_runs(None, 30, name)
if not runs:
    st.caption("No runs yet.")
else:
    st.dataframe(pd.DataFrame([{"": common.ICON.get(r["state"], ""), "kind": r["kind"], "started": common.ts(r["started"]),
                                "took": common.duration(r), "state": r["state"], "last line": r["last_line"][:90], "run": r["run_id"]}
                               for r in runs]), use_container_width=True, hide_index=True)
    pick = st.selectbox("Open a run's log", [r["run_id"] for r in runs], key="hist_pick")
    if pick:
        common.show_run(pick, name, "hist", refresh=False, lines=200)
