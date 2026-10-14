import streamlit as st

from brain import jobs_db, profiles, taskrunner, uidata
from ui import common

st.header("Resume Builder")
name = common.active_profile()
common.llm_banner()
rows = jobs_db.list_jobs(decision=["liked", "applied", "interview", "offer", "new"], ranked=True, limit=300, name=name) \
    or jobs_db.list_jobs(limit=100, name=name)
if not rows:
    st.info("No jobs yet. Discover and rank some jobs first.")
    common.page_link("pages/4_Run.py", "Go to Run", "▶️")
    st.stop()
ids = [r["job_id"] for r in rows]
default = ids.index(st.session_state["sel_job"]) if st.session_state.get("sel_job") in ids else 0
label = lambda i: next(f"{r['company'] or '?'} - {r['title'] or '?'}  [{r['decision']}]" for r in rows if r["job_id"] == i)  # noqa: E731
jid = st.selectbox("Job", ids, index=default, format_func=label)
st.session_state["sel_job"] = jid
job = jobs_db.get_job(jid, name)
st.markdown(f"[Original posting]({job['url']})")

engine = st.radio("Resume engine", ["career-ops (built-in, fast)", "Resume-Matcher", "Both side by side"], horizontal=True)
eng = {"career-ops (built-in, fast)": "career-ops", "Resume-Matcher": "resume-matcher", "Both side by side": "both"}[engine]
st.caption("Resume-Matcher starts and stops by itself while it works; it needs a model that can answer in strict JSON "
           "(set in Setup > Other settings). The built-in engine works with any model.")
live = taskrunner.is_running("tailor", name)
if st.button("Create tailored resume", type="primary", disabled=bool(live) or common.key_missing()):
    common.start_task("tailor", ["tailor", jid, "--engine", eng], name, "tailor_run")
rid = st.session_state.get("tailor_run") or (live["run_id"] if live else None)
if rid:
    common.show_run(rid, name, "tailor")

st.subheader("Generated resumes for this job")
files = uidata.resumes_for_job(jid, name)
if not files:
    st.caption("None yet.")
cols = st.columns(len(files) or 1)
for col, f in zip(cols, files):
    with col:
        st.markdown(f"**{f['engine']}**  \n{f['modified']} - {f['size_kb']} KB")
        data = open(f["path"], "rb").read()
        st.download_button("Download PDF", data, file_name=f"{name}-{jid}-{f['engine']}.pdf", mime="application/pdf", key=f"dl-{f['engine']}")
        try:
            st.pdf(data, height=600)
        except Exception:  # noqa: BLE001  (PDF viewer component not installed)
            st.caption("Preview not available here - download the PDF to view it.")

st.subheader("Keyword check")
cv = profiles.read_file(name, "cv.md")
km = uidata.keyword_match(job.get("description") or "", cv)
c1, c2 = st.columns(2)
c1.markdown("**In the job text and in your CV**")
c1.write(", ".join(km["found"]) or "-")
c2.markdown("**In the job text but not in your CV** (add the ones that are true for you)")
c2.write(", ".join(km["missing"]) or "-")
