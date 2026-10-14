"""Every page loads and its main actions work (Streamlit AppTest, temp profile, no real network or LLM)."""
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from brain import config, jobs_db, prep, profiles, schedule, sources, taskrunner
from tests.conftest import RESUME

UI = Path(__file__).resolve().parent.parent / "ui"
PAGES = ["0_Home", "1_Setup", "2_Profiles", "3_Sources", "4_Run", "5_Jobs", "6_Resume", "7_Prep", "8_Schedule", "9_Logs"]
NEEDS_PROFILE = ["0_Home", "3_Sources", "4_Run", "5_Jobs", "6_Resume", "7_Prep", "8_Schedule"]


def page(name, t=30):
    return AppTest.from_file(str(UI / "pages" / f"{name}.py"), default_timeout=t)


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    """No network: spend lookups and notifications are stubbed; brain/.env is a temp file."""
    env = tmp_path / ".env"
    env.write_text("# test\nOPENROUTER_API_KEY=k\nOPENROUTER_MODELS=a/one,b/two,c/three\nOPENROUTER_PAID_FALLBACK=p/one\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    for k in ("OPENROUTER_API_KEY", "OPENROUTER_MODELS", "OPENROUTER_PAID_FALLBACK"):
        monkeypatch.delenv(k, raising=False)
    from dotenv import dotenv_values
    for k, v in dotenv_values(env).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(schedule, "cron_status", lambda: {"installed": False, "detail": "no daily entry in crontab"})
    monkeypatch.setattr(schedule, "windows_available", lambda: False)
    monkeypatch.setattr(schedule, "cron_service_running", lambda: True)
    from brain import uidata
    monkeypatch.setattr(uidata, "followups_due", lambda name=None: [])
    return env


def seed(name, n=3):
    jobs_db.upsert_jobs([{"title": f"AI Engineer {i}", "company": f"Co{i}", "url": f"https://example.com/job/{i}", "location": "Bengaluru",
                          "description": f"Python Kubernetes RAG role {i}", "source": "remoteok"} for i in range(n)], name)
    ids = [j["job_id"] for j in jobs_db.list_jobs(name=name, order="found_at desc")]
    for i, jid in enumerate(ids):
        jobs_db.set_rank(jid, 4.5 - i * 0.5, None, name)
    return ids


# ------------------------------------------------------------------ every page loads
@pytest.mark.parametrize("p", PAGES)
def test_page_loads_with_profile(p, active):
    seed(active)
    at = page(p).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("p", NEEDS_PROFILE)
def test_pages_without_profile_show_call_to_action(p, env):
    at = page(p).run()
    assert not at.exception
    assert any("no active profile" in i.value.lower() for i in at.info)


@pytest.mark.parametrize("p", ["1_Setup", "2_Profiles", "9_Logs"])
def test_setup_pages_work_without_profile(p, env):
    assert not page(p).run().exception


def test_app_shell_boots(active):
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.selectbox[0].value == active


# ------------------------------------------------------------------ Setup
def test_setup_model_order_saved_to_env_and_config(active, quiet):
    at = page("1_Setup").run()
    at.button(key="free-up-1").click().run()                      # move b/two above a/one
    at.button(key="free-save").click().run()
    assert config.models()[:3] == ["b/two", "a/one", "c/three"]
    assert "OPENROUTER_MODELS=b/two,a/one,c/three" in quiet.read_text()
    assert quiet.read_text().startswith("# test")


def test_setup_add_and_remove_model(active, quiet):
    at = page("1_Setup").run()
    at.text_input(key="paid-new").input("x/new").run()
    at.button(key="paid-add").click().run()
    at.button(key="paid-save").click().run()
    assert config.paid_models() == ["p/one", "x/new"]
    at.button(key="paid-rm-0").click().run()
    at.button(key="paid-save").click().run()
    assert config.paid_models() == ["x/new"]


def test_setup_save_key_never_displayed(active, quiet):
    at = page("1_Setup").run()
    at.text_input(key="new_key").input("secret-123").run()
    at.button[0].click().run()
    assert "OPENROUTER_API_KEY=secret-123" in quiet.read_text()
    assert not any("secret-123" in str(m.value) for m in at.markdown)


def test_setup_test_key_button_uses_health(active, monkeypatch):
    from brain import health
    monkeypatch.setattr(health, "check", lambda: {"ok": True, "key_valid": True, "model_used": "m/x", "latency_s": 1.2, "error": None})
    at = page("1_Setup").run()
    next(b for b in at.button if b.label == "Test key").click().run()
    assert any("m/x" in s.value for s in at.success)


def test_setup_telegram_test_message(active, monkeypatch):
    from brain import notify
    monkeypatch.setattr(notify, "send_telegram", lambda text, *a, **k: {"ok": True, "detail": "sent 1 message"})
    at = page("1_Setup").run()
    next(b for b in at.button if b.label == "Send test message").click().run()
    assert any("sent" in s.value for s in at.success)


def test_setup_settings_saved_and_validated(active, quiet):
    at = page("1_Setup").run()
    at.text_input(key="daily_time").input("25:99").run()
    next(b for b in at.button if b.label == "Save settings").click().run()
    assert at.error
    at.text_input(key="daily_time").input("21:30").run()
    next(b for b in at.button if b.label == "Save settings").click().run()
    assert "DAILY_TIME=21:30" in quiet.read_text()


# ------------------------------------------------------------------ Profiles
def test_profile_create_from_pasted_cv_edit_salary_switch_duplicate(env):
    at = page("2_Profiles").run()
    at.text_input(key="new_name").input("ui1").run()
    at.text_area(key="cv_paste").input(RESUME.read_text()).run()
    at.text_input(key="create_form-min_base_salary").input("25 LPA")          # form values commit on submit
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    assert "ui1" in profiles.list_profiles() and profiles.get_active() == "ui1"
    assert profiles.load_profile("ui1")["prefs"]["min_base_salary"] == 2500000
    # edit salary
    at = page("2_Profiles").run()
    at.text_input(key="edit_form-min_base_salary").input("30 LPA")
    next(b for b in at.button if b.label == "Save").click().run()
    assert profiles.load_profile("ui1")["prefs"]["min_base_salary"] == 3000000
    # duplicate, then switch
    at = page("2_Profiles").run()
    at.text_input(key="dup_name").input("ui2").run()
    next(b for b in at.button if b.label == "Duplicate").click().run()
    assert "ui2" in profiles.list_profiles()
    at = page("2_Profiles").run()
    at.selectbox(key="prof_sel").select("ui2").run()
    next(b for b in at.button if b.label == "Activate").click().run()
    assert profiles.get_active() == "ui2"


def test_profile_create_rejects_bad_salary_and_missing_name(env):
    at = page("2_Profiles").run()
    at.text_area(key="cv_paste").input(RESUME.read_text()).run()
    at.text_input(key="create_form-min_base_salary").input("lots")
    next(b for b in at.button if b.label == "Save").click().run()
    msgs = " ".join(e.value for e in at.error)
    assert "could not read" in msgs and "Profile name" in msgs
    assert profiles.list_profiles() == []


def test_profile_invalid_yaml_rejected(active):
    at = page("2_Profiles").run()
    at.text_area(key=f"file-{active}-profile.yml").input("a: [unclosed").run()
    at.button(key="save-profile.yml").click().run()
    assert any("Invalid YAML" in e.value for e in at.error)


def test_profile_valid_edit_saved_with_backup(active):
    at = page("2_Profiles").run()
    at.text_area(key=f"file-{active}-_profile.md").input("# my notes\nhello").run()
    at.button(key="save-_profile.md").click().run()
    assert profiles.read_file(active, "_profile.md").startswith("# my notes")
    assert not at.error


def test_profile_trash_restore(active):
    profiles.duplicate_profile(active, "gone")
    profiles.delete_profile("gone")
    at = page("2_Profiles").run()
    btn = next(b for b in at.button if b.label == "Restore")
    btn.click().run()
    assert "gone" in profiles.list_profiles()


# ------------------------------------------------------------------ Sources
def test_sources_preview_add_and_duplicates(active):
    links = "https://remoteok.com/remote-ai-jobs\nhttps://boards.greenhouse.io/acme/jobs/12345\nhttps://jobs.lever.co/beta/abcd-1234"
    at = page("3_Sources").run()
    at.text_area(key="src_text").input(links).run()
    assert at.dataframe, "preview table missing"
    assert len(at.dataframe[0].value) == 3
    next(b for b in at.button if b.label == "Add these sources").click().run()
    assert len(sources.list_sources(name=active)) == 3
    at = page("3_Sources").run()
    at.text_area(key="src_text").input(links).run()
    assert list(at.dataframe[0].value["already added"]) == ["yes"] * 3


def test_sources_no_links_warns(active):
    at = page("3_Sources").run()
    at.text_area(key="src_text").input("no links here").run()
    assert at.warning


def test_sources_quick_add_builds_url(active):
    at = page("3_Sources").run()
    at.selectbox(key="qa_board").select("linkedin").run()
    at.text_input(key="qa_kw").input("ml engineer").run()
    assert any("linkedin.com/jobs/search" in c.value for c in at.code)


# ------------------------------------------------------------------ Run (fake runner, no subprocess)
@pytest.fixture
def fake_start(monkeypatch, active):
    calls = []

    def start(kind, argv, profile=None):
        calls.append((kind, list(argv)))
        rid, rd, st = taskrunner._new_run(kind, profile, argv, None)
        st.update(state="succeeded", finished=time.time(), exit_code=0, last_line="done",
                  stages={"health": {"status": "ok", "detail": "model x", "at": 0}, "rank": {"status": "ok", "detail": "2 ranked", "at": 0}})
        taskrunner._write(rd, st)
        return rid

    monkeypatch.setattr(taskrunner, "start", start)
    return calls


def test_run_page_discover_and_rank_start_tasks(active, fake_start):
    at = page("4_Run").run()
    next(b for b in at.button if "manual" in b.label).click().run()
    assert fake_start[-1][0] == "discover" and "--manual" in fake_start[-1][1]
    assert at.session_state["run_id"]
    assert any("Ranking" in str(m.value) and "2 ranked" in str(m.value) for m in at.markdown)
    next(b for b in at.button if "Rank new" in b.label).click().run()
    assert fake_start[-1][0] == "rank" and "--max" in fake_start[-1][1]


def test_run_page_busy_message(active, monkeypatch):
    def busy(*a, **k):
        raise taskrunner.Busy("A discover run is already in progress")
    monkeypatch.setattr(taskrunner, "start", busy)
    at = page("4_Run").run()
    next(b for b in at.button if "Full daily" in b.label).click().run()
    assert any("already in progress" in w.value for w in at.warning)


def test_run_page_disables_buttons_while_running(active):
    rid, rd, st = taskrunner._new_run("discover", active, ["x"], __import__("os").getpid())
    at = page("4_Run").run()
    assert all(b.disabled for b in at.button if b.label.startswith(("🔎", "🧮", "🚀")))


def test_run_history_lists_runs(active, fake_start):
    fake_start and None
    taskrunner.start("rank", ["x"], active)
    at = page("4_Run").run()
    assert at.dataframe and len(at.dataframe[0].value) >= 1


# ------------------------------------------------------------------ Jobs
def test_jobs_decisions_flow_and_history(active):
    ids = seed(active)
    at = page("5_Jobs").run()
    at.selectbox(key="pick-Inbox (new)").select(0).run()
    next(b for b in at.button if b.label == "👍 Like").click().run()
    assert jobs_db.get_job(ids[0], active)["decision"] == "liked"
    assert not at.exception
    at = page("5_Jobs").run()
    at.selectbox(key="pick-Liked").select(0).run()
    next(b for b in at.button if b.label == "✅ Applied").click().run()
    assert jobs_db.get_job(ids[0], active)["decision"] == "applied"
    assert [h["decision"] for h in jobs_db.history(ids[0], active)][-1] == "applied"


def test_jobs_notes_saved(active):
    ids = seed(active)
    at = page("5_Jobs").run()
    at.selectbox(key="pick-Inbox (new)").select(0).run()
    at.text_area(key=f"notes-{ids[0]}").input("call recruiter").run()
    next(b for b in at.button if b.label == "Save notes").click().run()
    assert jobs_db.get_job(ids[0], active)["notes"] == "call recruiter"


def test_jobs_filters_and_pagination(active):
    seed(active, 30)
    at = page("5_Jobs").run()
    assert any("30 job(s)" in c.value and "page 1 of 2" in c.value for c in at.caption)
    at.text_input(key="jobs_text").input("AI Engineer 7").run()
    assert any("1 job(s)" in c.value for c in at.caption)


def test_jobs_empty_states(active):
    at = page("5_Jobs").run()
    assert any("No new jobs" in i.value for i in at.info)


# ------------------------------------------------------------------ Resume
def test_resume_page_lists_files_and_starts_tailor(active, fake_start):
    ids = seed(active)
    from brain import tailor
    (tailor.out_dir(ids[0], active) / "career-ops.pdf").write_bytes(b"%PDF-1.4 test")
    at = page("6_Resume").run()
    assert not at.exception
    assert any("career-ops" in m.value for m in at.markdown)
    at.radio[0].set_value("Both side by side").run()
    next(b for b in at.button if b.label == "Create tailored resume").click().run()
    assert fake_start[-1][0] == "tailor" and "both" in fake_start[-1][1]


def test_resume_keyword_check(active):
    seed(active)
    at = page("6_Resume").run()
    assert any("kubernetes" in str(m.value) for m in at.markdown)


# ------------------------------------------------------------------ Prep
def test_prep_edit_save_reload(active, fake_start):
    ids = seed(active)
    jobs_db.set_decision(ids[0], "liked", name=active)
    prep.save_edit(ids[0], "cover", "Dear team,\nfirst draft", active)
    at = page("7_Prep").run()
    at.text_area(key=f"txt-cover-{ids[0]}").input("Dear team,\nedited by me").run()
    at.button(key=f"save-cover-{ids[0]}").click().run()
    assert prep.read(ids[0], "cover", active).startswith("Dear team,\nedited by me")
    at = page("7_Prep").run()
    assert at.text_area(key=f"txt-cover-{ids[0]}").value.strip().endswith("edited by me")


def test_prep_generate_all_five_kinds_start_tasks(active, fake_start):
    ids = seed(active)
    jobs_db.set_decision(ids[0], "applied", name=active)
    for kind in prep.KINDS:
        at = page("7_Prep").run()
        at.button(key=f"gen-{kind}-{ids[0]}").click().run()
        assert fake_start[-1][0] == "prep" and kind in fake_start[-1][1]
    assert len(fake_start) == 5


def test_prep_mark_applied(active):
    ids = seed(active)
    jobs_db.set_decision(ids[0], "liked", name=active)
    at = page("7_Prep").run()
    next(b for b in at.button if "I applied" in b.label).click().run()
    assert jobs_db.get_job(ids[0], active)["decision"] == "applied"


# ------------------------------------------------------------------ Schedule
def test_schedule_install_and_remove(active, quiet, monkeypatch):
    calls = []
    monkeypatch.setattr(schedule, "cron_install", lambda w: calls.append(("install", w)) or {"line": f"0 20 * * * run  # {w}"})
    monkeypatch.setattr(schedule, "cron_remove", lambda: calls.append(("remove",)) or True)
    at = page("8_Schedule").run()
    at.text_input(key="sched_time").input("20:00").run()
    next(b for b in at.button if b.label.startswith("Install / update")).click().run()
    assert calls[0] == ("install", "20:00") and "DAILY_TIME=20:00" in quiet.read_text()
    next(b for b in at.button if b.label == "Remove the schedule").click().run()
    assert ("remove",) in calls


def test_schedule_rejects_bad_time(active):
    at = page("8_Schedule").run()
    at.text_input(key="sched_time").input("7pm").run()
    assert at.error
    assert next(b for b in at.button if b.label.startswith("Install / update")).disabled


def test_schedule_run_now(active, fake_start):
    at = page("8_Schedule").run()
    next(b for b in at.button if b.label == "Run the daily job now").click().run()
    assert fake_start[-1][0] == "daily"


# ------------------------------------------------------------------ Home / Logs
def test_home_like_dismiss_buttons(active, tmp_path):
    ids = seed(active)
    rp = tmp_path / "001-x.md"
    rp.write_text("# Report\n")
    from brain import digest
    monkey_rows = [{**jobs_db.get_job(ids[0], active), "rank": 1, "chance": "High", "why": []}]
    at = page("0_Home")
    import brain.digest as d
    orig = d.top
    d.top = lambda n=10, name=None, **f: monkey_rows
    try:
        at.run()
        at.button(key=f"like-{ids[0]}").click().run()
    finally:
        d.top = orig
    assert jobs_db.get_job(ids[0], active)["decision"] == "liked"


def test_home_shows_attention_when_key_missing(active, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    at = page("0_Home").run()
    assert any("key is missing" in e.value for e in at.error)


def test_logs_restore_backup_and_export(active):
    profiles.write_file(active, "_profile.md", "v1")
    profiles.write_file(active, "_profile.md", "v2")
    at = page("9_Logs").run()
    assert not at.exception
    next(b for b in at.button if b.label == "Prepare an export of the active profile").click().run()
    assert at.session_state["export_bytes"][0] == active


def test_jobs_page_copes_with_1000_plus_jobs(active):
    import time as t
    seed(active, 1200)
    t0 = t.time()
    at = page("5_Jobs", 60).run()
    assert not at.exception
    assert any("1200 job(s)" in c.value and "page 1 of 48" in c.value for c in at.caption)
    assert t.time() - t0 < 20


def test_start_script_and_ui_command_exist():
    import hire
    root = Path(__file__).resolve().parent.parent
    assert (root / "start_ui.sh").stat().st_mode & 0o111
    assert callable(hire.cmd_ui)
