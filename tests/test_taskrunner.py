import sys
import time

import pytest

from brain import taskrunner


def _wait(rid, profile, secs=20):
    t0 = time.time()
    while time.time() - t0 < secs:
        st = taskrunner.get(rid, profile)
        if st and st["state"] not in taskrunner.LIVE:
            return st
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def py(code):
    return [sys.executable, "-c", code]


def test_success_with_stage_parsing(active):
    rid = taskrunner.start("tailor", py("print('[stage] health ok model x'); print('[stage] rank running 1/2 A'); print('done')"), active)
    st = _wait(rid, active)
    assert st["state"] == "succeeded" and st["exit_code"] == 0
    assert st["stages"]["health"]["status"] == "ok" and st["stages"]["rank"]["detail"] == "1/2 A"
    assert st["last_line"] == "done"
    assert taskrunner.tail(rid, 5, active)[-1] == "done"


def test_failure(active):
    st = _wait(taskrunner.start("prep", py("import sys; print('boom'); sys.exit(3)"), active), active)
    assert st["state"] == "failed" and st["exit_code"] == 3 and st["last_line"] == "boom"


def test_cancel(active):
    rid = taskrunner.start("tailor", py("import time; print('start', flush=True); time.sleep(60)"), active)
    t0 = time.time()
    while "start" not in " ".join(taskrunner.tail(rid, 5, active)) and time.time() - t0 < 10:
        time.sleep(0.1)
    assert taskrunner.cancel(rid, active)
    st = _wait(rid, active)
    assert st["state"] == "cancelled"
    assert not taskrunner.cancel(rid, active)


def test_single_flight(active):
    rid = taskrunner.start("discover", py("import time; time.sleep(30)"), active)
    try:
        with pytest.raises(taskrunner.Busy):
            taskrunner.start("rank", py("print(1)"), active)
        assert taskrunner.is_running("discover", active)["run_id"] == rid
        taskrunner.start("tailor", py("print(1)"), active)           # other kinds are not blocked
    finally:
        taskrunner.cancel(rid, active)
        _wait(rid, active)
    assert taskrunner.is_running("discover", active) is None


def test_list_runs_filters_and_orders(active):
    a = taskrunner.start("tailor", py("print(1)"), active)
    _wait(a, active)
    time.sleep(1.1)
    b = taskrunner.start("prep", py("print(2)"), active)
    _wait(b, active)
    ids = [r["run_id"] for r in taskrunner.list_runs(profile=active)]
    assert ids[:2] == [b, a]
    assert [r["run_id"] for r in taskrunner.list_runs("tailor", profile=active)] == [a]


def test_dead_process_is_marked_failed(active):
    rid, rd, st = taskrunner._new_run("rank", active, ["x"], 999999)
    assert taskrunner.get(rid, active)["state"] == "failed"


def test_recording_context_captures_cli_output(active, capsys):
    with taskrunner.recording("daily", active) as rid:
        print("[stage] sync ok 3 queued")
        print("hello")
    st = taskrunner.get(rid, active)
    assert st["state"] == "succeeded" and st["stages"]["sync"]["detail"] == "3 queued"
    assert "hello" in "\n".join(taskrunner.tail(rid, 10, active))


def test_recording_marks_failure_and_exit_code(active):
    with pytest.raises(SystemExit):
        with taskrunner.recording("daily", active) as rid:
            raise SystemExit(2)
    assert taskrunner.get(rid, active)["state"] == "failed"
    with pytest.raises(RuntimeError):
        with taskrunner.recording("rank", active) as rid2:
            raise RuntimeError("bad")
    st = taskrunner.get(rid2, active)
    assert st["state"] == "failed" and "bad" in st["last_line"]


def test_recording_is_noop_inside_ui_run(active, monkeypatch):
    monkeypatch.setenv("AIHIRE_RUN_ID", "x")
    with taskrunner.recording("daily", active) as rid:
        assert rid is None
