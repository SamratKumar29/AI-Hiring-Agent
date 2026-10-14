import pandas as pd
import streamlit as st

from brain import budget, digest, jobs_db, profiles, taskrunner, uidata
from ui import common

st.header("Home")
name = common.active_profile()
prefs = profiles.load_profile(name)["prefs"]

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    st.subheader(f"👤 {name}")
    st.caption(f"{', '.join(prefs.get('target_roles', [])[:3]) or 'no target roles'}  |  "
               f"{', '.join(prefs.get('locations', [])[:3]) or 'any location'}  |  "
               f"min {profiles.format_money(prefs.get('min_base_salary'), prefs.get('currency', 'INR')) if prefs.get('min_base_salary') else 'not set'}")
with c2:
    h = st.session_state.get("llm_health")
    st.metric("AI", h["model"] if h and h.get("ok") else ("check failed" if h else "not checked"))
    st.caption("Use the sidebar button to check the models.")
with c3:
    runs = taskrunner.list_runs(None, 1, name)
    last = runs[0] if runs else None
    st.metric("Last run", f"{common.ICON.get(last['state'], '')} {last['kind']}" if last else "none yet")
    st.caption(f"Next scheduled: {uidata.next_run_text()}")

k = uidata.kpis(name)
cols = st.columns(6)
for col, (label, key) in zip(cols, [("New today", "new_today"), ("Waiting to rank", "waiting"), ("Ranked", "ranked"),
                                    ("Liked", "liked"), ("Applied", "applied"), ("Interviews/offers", "interviews")]):
    col.metric(label, k[key])

left, right = st.columns([3, 2])
with left:
    st.subheader("Top ranked jobs")
    top = digest.top(10, name)
    if not top:
        st.info("Nothing ranked yet. Add sources, then run Discover and Rank.")
        common.page_link("pages/3_Sources.py", "Add job sources", "🔗")
        common.page_link("pages/4_Run.py", "Run discovery and ranking", "▶️")
    for it in top:
        with st.container(border=True):
            a, b, c, d = st.columns([6, 1, 1, 1])
            a.markdown(f"**{it['rank']}. {it.get('company') or '?'} - {it.get('title') or '?'}**  \n"
                       f"score {it.get('rank_score')} | {it.get('chance', '?')} chance | {it.get('location') or '-'} | "
                       f"[posting]({it['url']})")
            if b.button("👍", key=f"like-{it['job_id']}", help="Like"):
                jobs_db.set_decision(it["job_id"], "liked", name=name)
                st.rerun()
            if c.button("👎", key=f"dis-{it['job_id']}", help="Dismiss"):
                jobs_db.set_decision(it["job_id"], "dismissed", name=name)
                st.rerun()
            d.caption(it["decision"])
with right:
    st.subheader("Needs attention")
    items = uidata.needs_attention(name)
    if not items:
        st.success("Everything looks fine.")
    for i in items:
        {"error": st.error, "warning": st.warning, "info": st.info}[i["level"]](i["text"] + f"  (page: {i['page']})")
    st.subheader("OpenRouter spend")
    u = budget.usage()
    if u["ok"]:
        st.metric("This month", f"${u['monthly']:.2f}", help=f"Guard stops paid work at ${budget.monthly_limit():.2f} (0 = off)")
    else:
        st.caption(f"Spend not available ({u['error']})")
