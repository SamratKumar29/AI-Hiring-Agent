import os

import pytest

from brain import config, daily, digest, discover, jobs_db, llm, notify, profiles, rank
from tests.report_samples import report


@pytest.fixture
def d(active, tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(daily, "LOCK", tmp_path / "daily.lock")
    sent = []
    monkeypatch.setattr(notify, "send", lambda s, b: (sent.append((s, b)) or {"telegram": {"ok": True, "detail": "1 message(s) sent"},
                                                                             "email": {"ok": False, "skipped": True, "detail": "-"}}))
    monkeypatch.setattr(llm, "select_model", lambda *a, **k: {"model": "m/free", "tier": "free", "results": []})
    monkeypatch.setattr(discover, "run", lambda *a, **k: {"new_jobs": 3, "queued": 3, "stages": {"boards": {"status": "ok", "detail": "x"}}})
    monkeypatch.setattr(rank, "run", lambda *a, **k: {"ranked": 0, "failed": 0, "remaining": 0, "stopped_early": False})
    return type("D", (), {"sent": sent, "tmp": tmp_path})


def seed_ranked(active, n=3):
    ids = []
    for i in range(n):
        url = f"https://x.com/jobs/{500000 + i}"
        jobs_db.upsert_jobs([{"url": url, "title": f"Role {i}", "company": f"Co{i}", "location": "Bengaluru", "source": "t"}], name=active)
        jid = jobs_db.job_id(url)
        f = profiles.workspace_path(active, "reports") / f"{i + 1:03d}-co{i}-2026-10-13.md"
        f.write_text(report(score=f"4.{i}", company=f"Co{i}"), encoding="utf-8")
        digest.rank_job(jid, f, active)
        ids.append(jid)
    return ids


def test_happy_path_sends_top_jobs_and_remembers_them(active, d):
    seed_ranked(active)
    r = daily.run(active)
    assert r["exit"] == 0 and r["sent"] == 3
    subject, body = d.sent[0]
    assert subject == "Job hunt digest (3 new)" and "Co2" in body and "https://x.com/jobs/500002" in body
    assert body.index("Co2") < body.index("Co0")                                 # best first
    assert "3 new job(s) found" in body
    assert (daily.LOG_DIR / f"daily-{__import__('time').strftime('%Y-%m-%d')}.log").exists()
    assert not daily.LOCK.exists()                                               # lock released


def test_second_run_only_sends_jobs_not_sent_before(active, d):
    seed_ranked(active, 2)
    daily.run(active)
    seed_ranked(active, 3)                                                       # one genuinely new job (index 2)
    daily.run(active)
    second = d.sent[1][1]
    assert "Co2" in second and "Co0" not in second and "Co1" not in second


def test_quiet_day_still_tells_you_it_ran(active, d):
    r = daily.run(active)
    assert r["exit"] == 0 and r["sent"] == 0
    assert "No new ranked matches today" in d.sent[0][1]


def test_llm_down_notifies_and_exits_2(active, d, monkeypatch):
    monkeypatch.setattr(llm, "select_model", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable({"m": "HTTP 429"})))
    called = []
    monkeypatch.setattr(discover, "run", lambda *a, **k: called.append(1))
    r = daily.run(active)
    assert r["exit"] == 2 and not called and "LLM unavailable" in d.sent[0][0]


def test_stage_failure_is_reported_in_message_and_exit_1(active, d, monkeypatch):
    monkeypatch.setattr(discover, "run", lambda *a, **k: {"new_jobs": 0, "queued": 0, "stages": {
        "boards": {"status": "failed", "detail": "network down"}, "health": {"status": "failed", "detail": "ignored"}}})
    r = daily.run(active)
    assert r["exit"] == 1 and "boards: network down" in d.sent[0][1] and "health" not in d.sent[0][1]


def test_rank_crash_does_not_stop_the_notification(active, d, monkeypatch):
    seed_ranked(active, 1)
    monkeypatch.setattr(rank, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("node missing")))
    r = daily.run(active)
    assert r["exit"] == 1 and r["sent"] == 1 and "rank: RuntimeError" in d.sent[0][1]


def test_failed_delivery_is_not_remembered_so_next_run_retries(active, d, monkeypatch):
    seed_ranked(active, 1)
    monkeypatch.setattr(notify, "send", lambda s, b: {"telegram": {"ok": False, "detail": "network"}, "email": {"ok": False, "skipped": True, "detail": "-"}})
    r = daily.run(active)
    assert r["exit"] == 1 and "notification not delivered" in r["problems"]
    assert daily._load_notified(active) == set()


def test_no_send_flag_sends_nothing_and_remembers_nothing(active, d):
    seed_ranked(active, 1)
    r = daily.run(active, send=False)
    assert d.sent == [] and r["exit"] == 0 and daily._load_notified(active) == set()


def test_lock_blocks_a_second_run_but_stale_lock_is_taken_over(active, d):
    daily.LOCK.write_text(str(os.getpid()))                                      # "another run" = a live pid
    r = daily.run(active)
    assert r["exit"] == 3 and d.sent == []
    daily.LOCK.write_text("999999")                                              # dead pid
    assert daily.run(active)["exit"] == 0
    daily.LOCK.write_text("garbage")
    assert daily.run(active)["exit"] == 0


def test_max_evals_defaults_from_env_and_is_passed_to_rank(active, d, monkeypatch):
    got = {}
    monkeypatch.setattr(rank, "run", lambda name, max_n, **k: got.update(n=max_n) or {"ranked": 0, "failed": 0, "remaining": 0, "stopped_early": False})
    monkeypatch.setattr(config, "get", lambda k, df="": "7" if k == "MAX_EVALS_PER_RUN" else df)
    daily.run(active)
    assert got["n"] == 7
    daily.run(active, max_evals=3)
    assert got["n"] == 3


def test_render_text_is_phone_friendly():
    t = digest.render_text([{"rank": 1, "rank_score": 4.5, "chance": "High", "company": "Acme", "title": "AI Eng",
                             "location": "Remote", "advertised_comp": "Rs 20 LPA", "why": ["+0.2 pay"], "url": "https://x.com/j"}], "HEAD", "FOOT")
    assert t.startswith("HEAD") and t.endswith("FOOT") and "1. 4.5/5 [High] Acme - AI Eng" in t and "|" in t and "https://x.com/j" in t
    assert "---" not in t


def test_save_env_keeps_comments_and_mode(tmp_path, monkeypatch):
    from brain import config
    f = tmp_path / ".env"
    f.write_text("# my comment\nA=1\nB=2\n")
    monkeypatch.setattr(config, "ENV_FILE", f)
    config.save_env({"A": "10", "C": "3", "B": None})
    assert f.read_text() == "# my comment\nA=10\nB=\nC=3\n"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
