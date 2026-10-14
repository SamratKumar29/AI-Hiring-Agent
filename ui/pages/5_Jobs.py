import pandas as pd
import streamlit as st

from brain import jobs_db, prep, profiles, reports
from ui import common

st.header("Jobs")
name = common.active_profile()
prefs = profiles.load_profile(name)["prefs"]
PAGE = 25

TABS = {"Inbox (new)": ["new"], "Liked": ["liked"], "Applied & later": ["applied", "interview", "offer", "rejected", "withdrawn"],
        "Dismissed": ["dismissed"], "All history": None}
tab_objs = st.tabs(list(TABS))

with st.expander("Filters", expanded=False):
    f1, f2, f3 = st.columns(3)
    min_score = f1.slider("Minimum rank score", 0.0, 5.0, 0.0, 0.1)
    text = f2.text_input("Search title, company, place or text", key="jobs_text")
    since = f3.date_input("Found since", value=None, key="jobs_since")
    g1, g2, g3 = st.columns(3)
    only_ranked = g1.checkbox("Only ranked jobs", value=False)
    meets = g2.checkbox("Pays at least my minimum salary", value=False,
                        help="Jobs whose salary is unknown are hidden when this is on.")
    srcs = ["all"] + sorted(jobs_db.stats(name)["by_source"])
    source = g3.selectbox("Source", srcs)


def fetch(decisions):
    kw = dict(decision=decisions, min_score=min_score or None, text=text or None, source=None if source == "all" else source,
              min_salary=prefs.get("min_base_salary") if meets else None, ranked=True if only_ranked else None,
              order="rank_score desc", limit=2000, name=name)
    rows = jobs_db.list_jobs(**kw)
    if since:
        rows = [r for r in rows if (r.get("found_at") or "")[:10] >= str(since)]
    return rows


def table(rows, key):
    if not rows:
        st.info("No jobs here yet." if key != "Inbox (new)" else "No new jobs. Run Discover and Rank on the Run page.")
        return None
    pages = max(1, (len(rows) + PAGE - 1) // PAGE)
    pg = st.number_input("Page", 1, pages, 1, key=f"pg-{key}") if pages > 1 else 1
    chunk = rows[(pg - 1) * PAGE: pg * PAGE]
    st.caption(f"{len(rows)} job(s)" + (f" - page {pg} of {pages}" if pages > 1 else ""))
    df = pd.DataFrame([{"score": r["rank_score"], "company": r["company"], "title": r["title"], "location": r["location"],
                        "salary": r["salary_text"] or "", "source": r["source"], "found": (r["found_at"] or "")[:10],
                        "status": r["decision"], "posting": r["url"]} for r in chunk])
    ev = st.dataframe(df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"df-{key}",
                      column_config={"posting": st.column_config.LinkColumn("posting", display_text="open"),
                                     "score": st.column_config.NumberColumn(format="%.2f")})
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        return chunk[sel[0]]
    pick = st.selectbox("Or choose a job to open", [None] + list(range(len(chunk))), key=f"pick-{key}",
                        format_func=lambda i: "-" if i is None else f"{chunk[i]['company'] or '?'} - {chunk[i]['title'] or '?'}")
    return chunk[pick] if pick is not None else None


def detail(job):
    jid = job["job_id"]
    st.divider()
    st.subheader(f"{job['company'] or '?'} - {job['title'] or '?'}")
    st.markdown(f"[Open the original posting]({job['url']})  |  status: **{job['decision']}**  |  score: {job['rank_score'] if job['rank_score'] is not None else 'not ranked'}")
    b = st.columns(7)
    for col, (label, dec) in zip(b, [("👍 Like", "liked"), ("👎 Dismiss", "dismissed"), ("✅ Applied", "applied"), ("🗣 Interview", "interview"),
                                     ("🎉 Offer", "offer"), ("❌ Rejected", "rejected"), ("↩ Back to new", "new")]):
        if col.button(label, key=f"dec-{dec}-{jid}", disabled=job["decision"] == dec, use_container_width=True):
            if dec == "applied":
                prep.mark_applied(jid, name)
            else:
                jobs_db.set_decision(jid, dec, name=name)
            st.rerun()
    n1, n2 = st.columns(2)
    if n1.button("📄 Build a tailored resume for this job", key=f"gores-{jid}"):
        st.session_state["sel_job"] = jid
        st.switch_page("pages/6_Resume.py")
    if n2.button("🎯 Application prep for this job", key=f"goprep-{jid}"):
        st.session_state["sel_job"] = jid
        st.switch_page("pages/7_Prep.py")
    t1, t2, t3, t4 = st.tabs(["Evaluation report", "Job description", "My notes", "History"])
    with t1:
        rp = job.get("report_path")
        if rp and common.md_file(rp):
            parsed = reports.parse_file(rp)
            if not parsed.get("ok"):
                st.warning("This report looks incomplete: " + "; ".join(parsed.get("problems", [])[:2]))
            st.markdown(common.md_file(rp))
        else:
            st.info("Not ranked yet. Use 'Rank new jobs' on the Run page.")
    with t2:
        st.write(job.get("description") or "(no description saved)")
    with t3:
        notes = st.text_area("Notes", value=job.get("notes") or "", key=f"notes-{jid}", height=150)
        if st.button("Save notes", key=f"sn-{jid}"):
            jobs_db.update_fields(jid, name, notes=notes)
            st.success("Saved.")
    with t4:
        hist = jobs_db.history(jid, name)
        st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True) if hist else st.caption("No status changes yet.")


chosen = None
for tab, (label, decs) in zip(tab_objs, TABS.items()):
    with tab:
        job = table(fetch(decs), label)
        if job:
            chosen = job
if chosen:
    detail(chosen)
