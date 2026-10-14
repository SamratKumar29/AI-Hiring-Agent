import difflib
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from brain import config, profiles, taskrunner, uidata
from ui import common

st.header("Profiles")
names = profiles.list_profiles()
active = profiles.get_active()
tabs = st.tabs(["Your profiles", "Create new", "Edit preferences", "Edit files", "Trash"])


def prefs_form(defaults: dict, key: str, cv_text: str = "") -> dict | None:
    """Renders the preference questions; returns the raw answers when the form is submitted."""
    guessed = {**profiles.guess_identity(cv_text), **defaults}
    raw = {}
    with st.form(key):
        cols = st.columns(2)
        for i, (k, prompt, default, kind) in enumerate(profiles.FIELDS):
            col = cols[i % 2]
            cur = guessed.get(k, default)
            if kind == "salary":
                cur = guessed.get(k + "_text") or (str(cur) if cur not in (None, "") else "")
            if isinstance(cur, list):
                cur = ", ".join(cur)
            if kind == "mode":
                opts = ["any", "remote", "hybrid", "onsite"]
                raw[k] = col.selectbox(prompt, opts, index=opts.index(str(cur).lower()) if str(cur).lower() in opts else 0, key=f"{key}-{k}")
            elif kind == "bool":
                raw[k] = col.checkbox(prompt, value=bool(cur) if isinstance(cur, bool) else str(cur).lower() in ("y", "yes", "true"), key=f"{key}-{k}")
            else:
                raw[k] = col.text_input(prompt, value=str(cur if cur is not None else ""), key=f"{key}-{k}")
        ok = st.form_submit_button("Save", type="primary")
    return raw if ok else None


# ------------------------------------------------------------------ list + actions
with tabs[0]:
    if not names:
        st.info("No profiles yet. Open the 'Create new' tab.")
    rows = []
    for n in names:
        try:
            p = profiles.load_profile(n)["prefs"]
        except Exception:  # noqa: BLE001
            continue
        rows.append({"": "★ active" if n == active else "", "profile": n, "created": p.get("created", ""),
                     "target roles": ", ".join(p.get("target_roles", [])[:3]),
                     "min salary": profiles.format_money(p.get("min_base_salary"), p.get("currency", "INR"))})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        sel = st.selectbox("Choose a profile to act on", names, index=names.index(active) if active in names else 0, key="prof_sel")
        a, b, c, d, e = st.columns(5)
        if a.button("Activate", disabled=sel == active, use_container_width=True):
            profiles.activate(sel, use_llm=False)
            st.rerun()
        new_dup = b.text_input("Copy as", key="dup_name", placeholder="new name", label_visibility="collapsed")
        if b.button("Duplicate", disabled=not new_dup.strip(), use_container_width=True):
            try:
                profiles.duplicate_profile(sel, new_dup)
                st.success(f"Created '{profiles.slug(new_dup)}'.")
                st.rerun()
            except (FileExistsError, ValueError) as ex:
                st.error(str(ex))
        new_nm = c.text_input("Rename to", key="ren_name", placeholder="new name", label_visibility="collapsed")
        if c.button("Rename", disabled=not new_nm.strip(), use_container_width=True):
            try:
                profiles.rename_profile(sel, new_nm)
                st.rerun()
            except (FileExistsError, ValueError) as ex:
                st.error(str(ex))

        @st.dialog("Regenerate profile files?")
        def regen_dialog(n):
            st.warning("This rewrites profile.yml, portals.yml and _profile.md from your preferences. "
                       "Hand edits are replaced (old versions are kept as backups).")
            ai = st.checkbox("Let the AI write the narrative parts (slower, uses credits)", value=False)
            if st.button("Regenerate now", type="primary"):
                if ai:
                    try:
                        taskrunner.start("profile", taskrunner.hire_argv("profile", "regenerate", n), n)
                        st.session_state["regen_started"] = n
                    except RuntimeError as ex:
                        st.error(str(ex))
                        return
                else:
                    profiles.generate_files(n, use_llm=False)
                st.rerun()

        @st.dialog("Delete this profile?")
        def delete_dialog(n):
            st.warning(f"'{n}' (CV, preferences, jobs, reports) moves to the Trash tab. You can restore it.")
            if st.button("Delete", type="primary"):
                profiles.delete_profile(n)
                st.rerun()

        if d.button("Regenerate files", use_container_width=True):
            regen_dialog(sel)
        if e.button("Delete", use_container_width=True):
            delete_dialog(sel)
        if st.session_state.get("regen_started"):
            st.info("AI regeneration is running in the background; see Logs & Maintenance for progress.")

# ------------------------------------------------------------------ create
with tabs[1]:
    st.subheader("1. Your CV")
    pname = st.text_input("Profile name", key="new_name", placeholder="e.g. samrat-ai")
    up = st.file_uploader("Upload your CV (.md .pdf .docx .txt)", type=["md", "pdf", "docx", "txt"], key="cv_up")
    pasted = st.text_area("...or paste the CV text", height=150, key="cv_paste")
    cv_path = None
    if up is not None or pasted.strip():
        suffix = Path(up.name).suffix if up is not None else ".md"
        tmp = Path(tempfile.mkdtemp()) / f"cv{suffix}"
        tmp.write_bytes(up.getvalue() if up is not None else pasted.encode("utf-8"))
        try:
            cv_text = profiles.read_resume(tmp)
            cv_path = tmp
            st.success(f"Read the CV ({len(cv_text)} characters).")
        except Exception as ex:  # noqa: BLE001
            st.error(f"Could not read that file: {ex}")
    if cv_path:
        st.subheader("2. Your preferences")
        st.caption("Pre-filled from your CV where possible. The minimum salary removes jobs that pay less.")
        raw = prefs_form({}, "create_form", cv_text)
        if raw is not None:
            prefs, problems = profiles.form_to_prefs(raw)
            if not pname.strip():
                problems.append("Profile name: enter a name at the top.")
            if problems:
                for pr in problems:
                    st.error(pr)
            else:
                try:
                    profiles.create_profile(pname, cv_path, prefs)
                    profiles.activate(pname, use_llm=False)
                    st.success(f"Profile '{profiles.slug(pname)}' created and activated.")
                    st.session_state["just_created"] = profiles.slug(pname)
                except FileExistsError as ex:
                    st.error(str(ex))
        if st.session_state.get("just_created"):
            n = st.session_state["just_created"]
            st.info("Basic profile files were generated. For richer, AI-written files press the button below (uses credits).")
            if st.button("Generate profile files with AI"):
                try:
                    st.session_state["gen_run"] = taskrunner.start("profile", taskrunner.hire_argv("profile", "regenerate", n), n)
                except RuntimeError as ex:
                    st.error(str(ex))
            if st.session_state.get("gen_run"):
                common.show_run(st.session_state["gen_run"], n, "gen")

# ------------------------------------------------------------------ edit prefs
with tabs[2]:
    if not active:
        st.info("Activate a profile first.")
    else:
        st.caption(f"Editing '{active}'")
        p = profiles.load_profile(active)
        raw = prefs_form(p["prefs"], "edit_form")
        if raw is not None:
            prefs, problems = profiles.form_to_prefs(raw)
            for pr in problems:
                st.error(pr)
            if not problems:
                profiles.update_preferences(active, prefs)
                st.session_state["prefs_saved"] = True
                st.success("Saved.")
        if st.session_state.get("prefs_saved"):
            if st.button("Regenerate portals.yml / profile.yml now (no AI)"):
                profiles.generate_files(active, use_llm=False, only=("profile.yml", "portals.yml"))
                st.success("Regenerated.")

# ------------------------------------------------------------------ edit files
with tabs[3]:
    if not active:
        st.info("Activate a profile first.")
    else:
        ftabs = st.tabs(list(profiles.EDITABLE_FILES))
        for ft, fname in zip(ftabs, profiles.EDITABLE_FILES):
            with ft:
                cur = profiles.read_file(active, fname)
                text = st.text_area(fname, value=cur, height=380, key=f"file-{active}-{fname}")
                c1, c2 = st.columns(2)
                if c1.button("Save file", key=f"save-{fname}"):
                    try:
                        profiles.write_file(active, fname, text)
                        st.success("Saved (the previous version is kept as a backup).")
                    except ValueError as ex:
                        st.error(str(ex))
                baks = [b for b in uidata.list_backups() if b["file"] == f"{active}-{fname}"]
                if baks and c2.checkbox("Show changes since the last backup", key=f"diff-{fname}"):
                    old = Path(baks[0]["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
                    diff = "\n".join(difflib.unified_diff(old, cur.splitlines(), "previous", "current", lineterm=""))
                    st.code(diff or "(no changes)", language="diff")

# ------------------------------------------------------------------ trash
with tabs[4]:
    trash = profiles.list_trash()
    if not trash:
        st.info("The trash is empty.")
    for t in trash:
        c1, c2 = st.columns([4, 1])
        c1.write(f"**{t['profile']}**  deleted {t['deleted_at']}")
        if c2.button("Restore", key=f"rest-{t['trash_name']}"):
            try:
                profiles.restore_profile(t["trash_name"])
                st.rerun()
            except FileExistsError as ex:
                st.error(str(ex))
