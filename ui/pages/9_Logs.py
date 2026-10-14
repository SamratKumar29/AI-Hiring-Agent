import streamlit as st

from brain import config, profiles, taskrunner, uidata
from ui import common

st.header("Logs & Maintenance")
name = common.active_profile(required=False)
tabs = st.tabs(["Run logs", "App logs", "Backups & trash", "Export / import", "About"])

with tabs[0]:
    if not name:
        st.info("No profile yet.")
    else:
        runs = taskrunner.list_runs(None, 60, name)
        if not runs:
            st.caption("No runs recorded yet.")
        else:
            pick = st.selectbox("Run", [r["run_id"] for r in runs], format_func=lambda i: next(
                f"{common.ICON.get(r['state'], '')} {r['run_id']}  ({r['state']})" for r in runs if r["run_id"] == i))
            common.show_run(pick, name, "logs", refresh=False, lines=500)

with tabs[1]:
    files = uidata.log_files()
    if not files:
        st.caption("No app logs yet (daily runs write them to brain/data/logs).")
    else:
        f = st.selectbox("Log file", files, format_func=lambda p: p.name)
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
        st.code("\n".join(lines), language="text")

with tabs[2]:
    st.markdown("**Profile file backups** (made automatically before every overwrite)")
    baks = uidata.list_backups()
    if not baks:
        st.caption("No backups yet.")
    for b in baks[:30]:
        c1, c2 = st.columns([5, 1])
        c1.write(f"{b['when']}  -  {b['file']}")
        if name and b["file"].startswith(name + "-") and c2.button("Restore", key=f"rb-{b['when']}-{b['file']}"):
            try:
                uidata.restore_backup(b["path"], name)
                st.success("Restored.")
            except ValueError as e:
                st.error(str(e))
    st.markdown("**Deleted profiles**")
    for t in profiles.list_trash():
        c1, c2 = st.columns([5, 1])
        c1.write(f"{t['profile']}  deleted {t['deleted_at']}")
        if c2.button("Restore", key=f"rt-{t['trash_name']}"):
            try:
                profiles.restore_profile(t["trash_name"])
                st.rerun()
            except FileExistsError as e:
                st.error(str(e))

with tabs[3]:
    if name:
        if st.button("Prepare an export of the active profile"):
            import tempfile
            from pathlib import Path
            z = uidata.export_profile(name, Path(tempfile.mkdtemp()) / f"{name}.zip")
            st.session_state["export_bytes"] = (name, z.read_bytes())
        if st.session_state.get("export_bytes"):
            n, data = st.session_state["export_bytes"]
            st.download_button(f"Download {n}.zip", data, file_name=f"{n}.zip", mime="application/zip")
    up = st.file_uploader("Import a profile (.zip made by Export)", type=["zip"], key="imp_zip")
    new = st.text_input("Name for the imported profile (optional)", key="imp_name")
    if up is not None and st.button("Import"):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "in.zip"
        tmp.write_bytes(up.getvalue())
        try:
            st.success(f"Imported as '{uidata.import_profile(tmp, new or None)}'.")
        except (ValueError, FileExistsError) as e:
            st.error(str(e))

with tabs[4]:
    import platform
    import sys
    st.write(f"Python {sys.version.split()[0]} | Streamlit {st.__version__} | {platform.system()}")
    st.write(f"Project folder: `{config.ROOT_DIR}`")
    if st.button("Clear UI caches"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cleared.")
