from brain import config, doctor, profiles


def test_run_returns_well_formed_results(active, monkeypatch):
    monkeypatch.setattr(doctor, "check_career_ops", lambda: doctor._r("career-ops doctor", doctor.PASS, "ok"))
    res = doctor.run()
    assert res and all(set(r) == {"name", "status", "detail", "fix"} for r in res)
    assert all(r["status"] in (doctor.PASS, doctor.WARN, doctor.FAIL) for r in res)
    s = doctor.summary(res)
    assert sum(s.values()) == len(res)


def test_no_active_profile_fails_with_fix(env):
    r = doctor.check_profile()
    assert r[0]["status"] == doctor.FAIL and "profile create" in r[0]["fix"]


def test_active_profile_db_writable(active):
    r = {x["name"]: x for x in doctor.check_profile()}
    assert r["jobs.db writable"]["status"] == doctor.PASS


def test_missing_env_file_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "nope.env")
    assert doctor.check_env_file()["status"] == doctor.FAIL


def test_env_file_permissions_warn(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("X=1")
    f.chmod(0o644)
    monkeypatch.setattr(config, "ENV_FILE", f)
    assert doctor.check_env_file()["status"] == doctor.WARN
    f.chmod(0o600)
    assert doctor.check_env_file()["status"] == doctor.PASS


def test_notifications_warn_when_unset(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST"):
        monkeypatch.setenv(k, "")
    out = doctor.check_notifications()
    assert out[0]["status"] == doctor.WARN and "locally" in out[0]["detail"]


def test_hire_doctor_exit_code(active, monkeypatch, capsys):
    import hire
    monkeypatch.setattr(doctor, "run", lambda llm=False: [doctor._r("x", doctor.FAIL, "bad", "do y")])
    class A: llm = False
    assert hire.cmd_doctor(A()) == 1
    assert "fix: do y" in capsys.readouterr().out
    monkeypatch.setattr(doctor, "run", lambda llm=False: [doctor._r("x", doctor.WARN, "meh")])
    assert hire.cmd_doctor(A()) == 0
