import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from brain import sources, uidata
from ui import common

st.header("Job sources")
name = common.active_profile()
st.caption("Add job-board search links (LinkedIn, Indeed, Naukri, Wellfound, RemoteOK...), single job postings, company career pages, "
           "or a PDF / text file that contains such links.")

# ------------------------------------------------------------------ add
st.subheader("Add sources")
t1, t2, t3 = st.tabs(["Links or pasted text", "Upload a file", "Quick-add a board"])
items = []
with t1:
    text = st.text_area("Paste one or many links (or any text containing links)", height=120, key="src_text")
    if text.strip():
        items = [text]
with t2:
    up = st.file_uploader("PDF, Word, text, markdown, CSV or HTML file with links", type=["pdf", "docx", "txt", "md", "csv", "html"], key="src_file")
    if up is not None:
        tmp = Path(tempfile.mkdtemp()) / up.name
        tmp.write_bytes(up.getvalue())
        items = [str(tmp)]
with t3:
    board = st.selectbox("Board", list(uidata.BOARD_FORMS), format_func=uidata.BOARD_FORMS.get, key="qa_board")
    c1, c2 = st.columns(2)
    kw = c1.text_input("Search keywords", value="AI Engineer", key="qa_kw")
    loc = c2.text_input("Location", value="Bengaluru", key="qa_loc")
    if board in ("michaelpage", "multirecruit"):
        st.caption("This board's search address is a best guess - open the link once to check it, then add it.")
    try:
        url = uidata.board_search_url(board, kw, loc)
        st.code(url, language=None)
        if st.button("Use this link"):
            st.session_state["src_text"] = url
            st.rerun()
    except ValueError as e:
        st.warning(str(e))

if items:
    try:
        prev = sources.preview(items, name)
    except Exception as e:  # noqa: BLE001
        prev = []
        st.error(f"Could not read that: {e}")
    if prev:
        st.write(f"**Found {len(prev)} link(s). Check them before saving:**")
        st.dataframe(pd.DataFrame([{"type": p["type"], "board/company": p.get("board") or p.get("company") or "", "link": p["url"],
                                    "already added": "yes" if p["already_added"] else ""} for p in prev]),
                     use_container_width=True, hide_index=True)
        if st.button("Add these sources", type="primary"):
            r = sources.add(items, name)
            st.success(f"Added {len(r['added'])}, {len(r['duplicates'])} already known.")
            st.session_state.pop("src_text", None)
            st.rerun()
    elif items:
        st.warning("No links found in that input.")

# ------------------------------------------------------------------ list
st.subheader("Your sources")
rows = sources.list_sources(name=name)
if not rows:
    st.info("No sources yet. Add one above.")
else:
    types = ["all"] + sorted({r["type"] for r in rows})
    ftype = st.selectbox("Show", types, key="src_filter")
    shown = [r for r in rows if ftype == "all" or r["type"] == ftype]
    df = pd.DataFrame([{"enabled": r["enabled"], "type": r["type"], "board/company": r.get("board") or r.get("company") or "",
                        "link": r["url"], "last status": r.get("last_status", ""), "remove": False, "id": r["id"]} for r in shown])
    edited = st.data_editor(df, hide_index=True, use_container_width=True, key="src_editor",
                            disabled=["type", "board/company", "link", "last status", "id"],
                            column_config={"id": None})
    if st.button("Apply changes"):
        for _, row in edited.iterrows():
            if row["remove"]:
                sources.remove(row["id"], name)
            elif bool(row["enabled"]) != bool(next(r for r in shown if r["id"] == row["id"])["enabled"]):
                sources.set_enabled(row["id"], bool(row["enabled"]), name)
        st.rerun()
    st.caption("Tick 'remove' and press Apply to delete a source. Unticking 'enabled' keeps it but skips it.")
