"""Shared UI helpers. No business logic here: everything calls brain.*"""
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain import config, profiles, taskrunner  # noqa: E402

ICON = {"queued": "⏳", "running": "🔄", "succeeded": "✅", "failed": "❌", "cancelled": "🚫",
        "ok": "✅", "skipped": "⏭️"}
STAGE_ORDER = ["health", "job-scraper", "ai-job-scraper", "boards", "career-ops-scan", "import-inbox", "sync", "rank", "digest", "notify"]
STAGE_LABEL = {"health": "Health check", "job-scraper": "LinkedIn job-scraper", "ai-job-scraper": "Scheduled scraper",
               "boards": "Board scrapers", "career-ops-scan": "Company pages scan", "import-inbox": "Pasted links",
               "sync": "Filter and queue", "rank": "Ranking", "digest": "Digest", "notify": "Notification"}


def page_link(path: str, label: str, icon: str | None = None) -> None:
    try:
        st.page_link(path, label=label, icon=icon)
    except Exception:  # noqa: BLE001  (running a page on its own, e.g. in tests)
        st.caption(f"Open: {label}")


def active_profile(required: bool = True) -> str | None:
    name = profiles.get_active()
    if not name and required:
        st.info("You have no active profile yet. Create your first profile to start.")
        page_link("pages/2_Profiles.py", "Create your first profile", "👤")
        st.stop()
    return name


def key_missing() -> bool:
    try:
        config.api_key()
        return False
    except RuntimeError:
        return True


def llm_banner() -> None:
    """Warning shown on pages that need the AI model when the key is missing or the last check failed."""
    if key_missing():
        st.error("The OpenRouter key is missing, so AI features are disabled. Open Setup and paste your key.")
        page_link("pages/1_Setup.py", "Open Setup", "⚙️")
    elif st.session_state.get("llm_health", {}).get("ok") is False:
        st.warning("The last model check failed (" + str(st.session_state["llm_health"].get("error", ""))[:120] + "). "
                   "AI actions may fail. Open Setup > Models to check again.")


def ts(t) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(t)) if t else "-"


def duration(st_) -> str:
    end = st_.get("finished") or time.time()
    s = int(end - (st_.get("started") or end))
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def show_run(run_id: str, profile: str, key: str, refresh: bool = True, lines: int = 25) -> None:
    """Live status of one run: stage list, last log lines, Cancel. Refreshes itself every 2 s while it is running."""
    def body():
        s = taskrunner.get(run_id, profile)
        if not s:
            st.warning("This run could not be found.")
            return
        live = s["state"] in taskrunner.LIVE
        st.markdown(f"**{ICON.get(s['state'], '')} {s['kind']}** - {s['state']} - started {ts(s['started'])} - {duration(s)}")
        names = [n for n in STAGE_ORDER if n in s["stages"]] + [n for n in s["stages"] if n not in STAGE_ORDER]
        for n in names:
            e = s["stages"][n]
            st.write(f"{ICON.get(e['status'], '🔄')} **{STAGE_LABEL.get(n, n)}** {e['detail'][:160]}")
        with st.expander("Log", expanded=live):
            st.code("\n".join(taskrunner.tail(run_id, lines, profile)) or "(no output yet)", language="text")
        if live and st.button("Cancel this run", key=f"cancel-{key}-{run_id}"):
            taskrunner.cancel(run_id, profile)
            st.rerun()
        if not live and st.session_state.get(f"done-{run_id}") is None:
            st.session_state[f"done-{run_id}"] = True
            st.rerun()
    if refresh:
        st.fragment(run_every=2)(body)()
    else:
        body()


def start_task(kind: str, args: list, profile: str, state_key: str) -> None:
    """Start a background run and remember it for this page; shows a friendly error if one is already running."""
    try:
        st.session_state[state_key] = taskrunner.start(kind, taskrunner.hire_argv(*args, "--profile", profile), profile)
    except taskrunner.Busy as e:
        st.warning(str(e))
    except RuntimeError as e:
        st.error(str(e))


def md_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
