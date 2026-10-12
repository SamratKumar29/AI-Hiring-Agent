from brain import jobs_db, sources
from brain.scrapers import boards, michaelpage, remoteok, wellfound


def fake(monkeypatch, remote=None, mp=None, wf=None):
    monkeypatch.setattr(remoteok, "fetch", lambda roles, limit=50, **k: remote if remote is not None else [])
    monkeypatch.setattr(michaelpage, "fetch", lambda urls=None, **k: mp if mp is not None else [])
    monkeypatch.setattr(wellfound, "fetch", lambda urls=None, **k: wf if wf is not None else [])


ROW = lambda i, src: {"url": f"https://x.com/jobs/{i}", "title": f"T{i}", "company": "C", "source": src}  # noqa: E731


def test_only_boards_with_sources_run_plus_remoteok(active, monkeypatch):
    fake(monkeypatch, remote=[ROW(111111, "remoteok")], mp=[ROW(222222, "michaelpage")], wf=[ROW(333333, "wellfound")])
    sources.add("https://www.michaelpage.co.in/jobs/technology https://remoteok.com/remote-ai-jobs")
    r = boards.run("p")
    assert set(r["boards"]) == {"remoteok", "michaelpage"} and r["added"] == 2 and jobs_db.count(name="p") == 2
    assert {x["board"]: x["last_status"] for x in sources.list_sources("board_search", name="p")} == {
        "michaelpage": "1 found, 1 new", "remoteok": "1 found, 1 new"}


def test_remoteok_runs_without_source_only_for_remote_or_any(active, monkeypatch):
    fake(monkeypatch, remote=[ROW(111111, "remoteok")])
    assert boards.run("p")["boards"] == {}                       # profile is hybrid
    from brain import profiles
    profiles.update_preferences("p", {"work_mode": "remote"})
    assert boards.run("p")["boards"]["remoteok"]["added"] == 1


def test_second_run_adds_nothing(active, monkeypatch):
    fake(monkeypatch, remote=[ROW(111111, "remoteok")])
    sources.add("https://remoteok.com/remote-ai-jobs")
    boards.run("p")
    assert boards.run("p")["added"] == 0


def test_one_board_failing_does_not_stop_others(active, monkeypatch):
    fake(monkeypatch, remote=[ROW(111111, "remoteok")])
    monkeypatch.setattr(michaelpage, "fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503")))
    sources.add("https://www.michaelpage.co.in/jobs/technology https://remoteok.com/remote-ai-jobs")
    r = boards.run("p")
    assert r["boards"]["michaelpage"]["error"] == "503" and r["boards"]["remoteok"]["added"] == 1


def test_unsupported_boards_are_reported_with_reason(active, monkeypatch):
    fake(monkeypatch)
    sources.add("https://www.naukri.com/ai-engineer-jobs-in-bengaluru https://in.indeed.com/jobs?q=ai")
    r = boards.run("p")
    assert set(r["unsupported"]) == {"naukri", "indeed"} and "recaptcha" in r["unsupported"]["naukri"]
    assert all(s["last_status"].startswith("not scrapable") for s in sources.list_sources("board_search", name="p"))
