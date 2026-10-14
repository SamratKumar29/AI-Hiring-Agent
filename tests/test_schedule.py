import subprocess
from types import SimpleNamespace

import pytest

from brain import schedule

EXISTING = "MAILTO=me@x.com\n0 3 * * * /usr/bin/backup.sh\n"


@pytest.fixture
def fake_cron(monkeypatch):
    store = SimpleNamespace(text=EXISTING)

    def run(cmd, input=None, capture_output=None, text=None, **k):
        if cmd[:2] == ["crontab", "-l"]:
            return SimpleNamespace(returncode=0 if store.text else 1, stdout=store.text, stderr="no crontab")
        if cmd[:2] == ["crontab", "-"]:
            store.text = input
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(cmd)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(schedule.shutil, "which", lambda n: f"/usr/bin/{n}")
    return store


def test_parse_time_and_line():
    assert schedule.parse_time("08:00") == (8, 0) and schedule.parse_time(" 7:05 ") == (7, 5) and schedule.parse_time("23:59") == (23, 59)
    for bad in ("25:00", "8", "08:60", "noon", ""):
        with pytest.raises(ValueError):
            schedule.parse_time(bad)
    assert schedule.cron_line("08:30", "/x/run.sh") == "30 8 * * * /x/run.sh"


def test_install_preserves_other_entries_and_is_idempotent(fake_cron):
    schedule.cron_install("08:00")
    first = fake_cron.text
    assert "0 3 * * * /usr/bin/backup.sh" in first and "MAILTO=me@x.com" in first
    assert first.count("run_daily.sh") == 1 and "0 8 * * *" in first
    schedule.cron_install("09:15")
    assert fake_cron.text.count("run_daily.sh") == 1 and "15 9 * * *" in fake_cron.text and "0 8 * * * " not in fake_cron.text
    assert "0 3 * * * /usr/bin/backup.sh" in fake_cron.text


def test_status_and_remove(fake_cron):
    assert schedule.cron_status()["installed"] is False
    schedule.cron_install("08:00")
    st = schedule.cron_status()
    assert st["installed"] and st["line"].endswith("run_daily.sh")
    assert schedule.cron_remove() is True
    assert fake_cron.text == EXISTING.rstrip("\n") + "\n" and schedule.cron_status()["installed"] is False
    assert schedule.cron_remove() is False


def test_install_into_empty_crontab_and_remove_leaves_it_empty(fake_cron):
    fake_cron.text = ""
    schedule.cron_install("06:00")
    assert fake_cron.text.startswith(schedule.BEGIN)
    schedule.cron_remove()
    assert fake_cron.text == ""


def test_missing_crontab_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(schedule.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeError, match="apt install cron"):
        schedule.cron_install("08:00")


def test_run_daily_script_exists_and_is_executable():
    import os
    assert os.access(schedule.SCRIPT, os.X_OK)
    text = schedule.SCRIPT.read_text()
    assert "nvm.sh" in text and "hire.py daily" in text and "cron.log" in text


def test_windows_command_shape(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    cmd = schedule.windows_command("08:00")
    assert cmd[0] == "schtasks.exe" and "/SC" in cmd and "DAILY" in cmd and "08:00" in cmd
    assert cmd[cmd.index("/TR") + 1] == f"wsl.exe -d Ubuntu -e {schedule.SCRIPT}"
