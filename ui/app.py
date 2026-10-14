"""AI Hiring Agent - web interface.  Start with:  ./venv/bin/python hire.py ui"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from brain import health, llm, profiles, taskrunner  # noqa: E402
from ui import common  # noqa: E402

st.set_page_config(page_title="AI Hiring Agent", page_icon="💼", layout="wide")

PAGES = [
    st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True),
    st.Page("pages/1_Setup.py", title="Setup", url_path="setup", icon="⚙️"),
    st.Page("pages/2_Profiles.py", title="Profiles", url_path="profiles", icon="👤"),
    st.Page("pages/3_Sources.py", title="Sources", url_path="sources", icon="🔗"),
    st.Page("pages/4_Run.py", title="Run", url_path="run", icon="▶️"),
    st.Page("pages/5_Jobs.py", title="Jobs", url_path="jobs", icon="📋"),
    st.Page("pages/6_Resume.py", title="Resume Builder", url_path="resume", icon="📄"),
    st.Page("pages/7_Prep.py", title="Application Prep", url_path="prep", icon="🎯"),
    st.Page("pages/8_Schedule.py", title="Schedule", url_path="schedule", icon="⏰"),
    st.Page("pages/9_Logs.py", title="Logs & Maintenance", url_path="logs", icon="🧰"),
]


def sidebar() -> None:
    with st.sidebar:
        st.title("💼 AI Hiring Agent")
        names = profiles.list_profiles()
        active = profiles.get_active()
        if names:
            idx = names.index(active) if active in names else 0
            chosen = st.selectbox("Profile", names, index=idx, key="sidebar_profile")
            if chosen != active:
                try:
                    profiles.activate(chosen, use_llm=False)
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not switch profile: {e}")
        else:
            st.caption("No profile yet.")
        h = st.session_state.get("llm_health")
        if common.key_missing():
            st.error("API key missing")
        elif h and h.get("ok"):
            st.success(f"AI ready: {h['model']}")
        elif h:
            st.warning("AI check failed")
        else:
            st.caption("AI model not checked yet")
        if not common.key_missing() and st.button("Check AI now", use_container_width=True):
            with st.spinner("Asking the models..."):
                try:
                    sel = llm.select_model(force=True)
                    st.session_state["llm_health"] = {"ok": True, "model": sel["model"]}
                except llm.LLMUnavailable as e:
                    st.session_state["llm_health"] = {"ok": False, "error": str(e)}
            st.rerun()
        run = taskrunner.any_running(active) if active else None
        if run:
            st.info(f"🔄 {run['kind']} is running")


sidebar()
st.navigation(PAGES).run()
