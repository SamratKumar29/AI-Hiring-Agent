import tempfile
from pathlib import Path

import streamlit as st

from brain import jobs_db, prep, taskrunner, uidata
from ui import common

st.header("Application Prep")
name = common.active_profile()
common.llm_banner()
rows = jobs_db.list_jobs(decision=["applied", "interview", "offer", "liked"], limit=300, name=name) or jobs_db.list_jobs(limit=100, name=name)
if not rows:
    st.info("No jobs yet. Like or apply to a job first.")
    st.stop()
ids = [r["job_id"] for r in rows]
default = ids.index(st.session_state["sel_job"]) if st.session_state.get("sel_job") in ids else 0
label = lambda i: next(f"{r['company'] or '?'} - {r['title'] or '?'}  [{r['decision']}]" for r in rows if r["job_id"] == i)  # noqa: E731
jid = st.selectbox("Job", ids, index=default, format_func=label)
st.session_state["sel_job"] = jid
job = jobs_db.get_job(jid, name)

top = st.columns([3, 2])
with top[0]:
    st.markdown(f"[Original posting]({job['url']})  |  status: **{job['decision']}**")
    if job["decision"] in ("new", "liked") and st.button("✅ I applied to this job"):
        prep.mark_applied(jid, name)
        st.rerun()
with top[1]:
    hist = uidata.timeline(jid, name)
    st.caption("Timeline: " + (" → ".join(f"{h['decision']} ({h['at'][:10]})" for h in hist) or "no changes yet"))

TITLES = {"cover": "Cover letter", "interview": "Interview prep", "offer": "Offer & negotiation", "followup": "Follow-up email", "outreach": "Outreach"}
tabs = st.tabs([TITLES[k] for k in prep.KINDS])
live = taskrunner.is_running("prep", name)
for tab, kind in zip(tabs, prep.KINDS):
    with tab:
        existing = prep.read(jid, kind, name)
        extra_args = []
        if kind == "offer":
            offer = st.text_area("Paste the offer letter or contract (optional; without it you get a pre-offer negotiation brief)", key=f"offer-{jid}", height=100)
            if offer.strip():
                tmp = Path(tempfile.mkdtemp()) / "offer.txt"
                tmp.write_text(offer, encoding="utf-8")
                extra_args = ["--offer-file", str(tmp)]
        if st.button("Regenerate" if existing else "Generate", key=f"gen-{kind}-{jid}", disabled=bool(live) or common.key_missing(), type="primary"):
            common.start_task("prep", ["prep", jid, "--kind", kind, *extra_args], name, "prep_run")
        if st.session_state.get("prep_run"):
            common.show_run(st.session_state["prep_run"], name, f"prep-{kind}")
        if existing:
            text = st.text_area("Edit here", value=existing, height=420, key=f"txt-{kind}-{jid}")
            c1, c2 = st.columns(2)
            if c1.button("Save my edits", key=f"save-{kind}-{jid}"):
                prep.save_edit(jid, kind, text, name)
                st.success("Saved (the previous version is kept in the history folder).")
            c2.download_button("Download .md", text, file_name=f"{kind}-{jid}.md", key=f"dl-{kind}-{jid}")
            st.caption("To copy: select the text above and press Ctrl+C.")
        else:
            st.caption("Nothing generated yet.")

st.subheader("Follow-ups due")
due = uidata.followups_due(name)
if due:
    st.dataframe(due, use_container_width=True, hide_index=True)
else:
    st.caption("Nothing is due. (Follow-ups appear a week after you mark a job as applied.)")
