import pytest

from brain import discover, jobs_db, llm, nodeenv, pipeline_inbox, progress
from brain.scrapers import boards, career_ops_scan, manual, scheduled


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(llm, "select_model", lambda *a, **k: {"model": "m/free", "tier": "free", "results": []})
    monkeypatch.setattr(manual, "run", lambda n: {"ok": True, "added": 0, "log_tail": ""})
    monkeypatch.setattr(scheduled, "run", lambda n: {"ok": False, "skipped": True, "added": 0, "found": 0, "reason": "no key"})
    monkeypatch.setattr(boards, "run", lambda n: {"boards": {"remoteok": {"found": 1, "added": 1, "error": None}}, "unsupported": {"naukri": "x"}, "added": 1})
    monkeypatch.setattr(career_ops_scan, "scan", lambda n, since_days=2: {"ok": True, "log_tail": ""})


def test_scheduled_run_skips_manual_stage_and_reports_every_stage(active, stub):
    seen = []
    jobs_db.upsert_jobs([{"url": "https://x.com/jobs/111111", "title": "AI Eng", "company": "Acme", "source": "remoteok"}], name="p")
    r = discover.run("scheduled", on_stage=seen.append, quiet=True)
    assert [s for s in r["stages"]] == list(discover.STAGES)
    assert r["stages"]["job-scraper"]["status"] == "skipped" and r["stages"]["ai-job-scraper"]["status"] == "skipped"
    assert r["stages"]["health"]["detail"] == "model m/free (free tier)" and r["queued"] == 1
    assert {(e["name"], e["status"]) for e in seen} >= {("health", "running"), ("sync", "ok"), ("job-scraper", "skipped")}
    assert pipeline_inbox.pending("p")[0].startswith("- [ ] https://x.com/jobs/111111")


def test_manual_mode_runs_linkedin_scraper(active, stub, monkeypatch):
    monkeypatch.setattr(manual, "run", lambda n: {"ok": True, "added": 3, "log_tail": ""})
    r = discover.run("manual", quiet=True)
    assert r["stages"]["job-scraper"] == {"status": "ok", "detail": "3 new", "added": 3}


def test_one_failing_stage_does_not_stop_the_rest(active, stub, monkeypatch):
    monkeypatch.setattr(boards, "run", lambda n: (_ for _ in ()).throw(RuntimeError("network down")))
    monkeypatch.setattr(llm, "select_model", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable({"m": "x"})))
    r = discover.run("scheduled", quiet=True)
    assert r["stages"]["boards"]["status"] == "failed" and "network down" in r["stages"]["boards"]["detail"]
    assert r["stages"]["health"]["status"] == "failed"
    assert r["stages"]["career-ops-scan"]["status"] == "ok" and r["stages"]["sync"]["status"] == "ok"


def test_stage_lines_are_parseable(active, stub, capsys):
    discover.run("scheduled")
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[stage]")]
    assert len(lines) >= 7 and all(progress.parse(l) for l in lines)
    assert progress.parse("[stage] boards ok remoteok:1 | not scrapable: naukri") == {
        "name": "boards", "status": "ok", "detail": "remoteok:1 | not scrapable: naukri"}
    assert progress.parse("random text") is None


def test_bad_mode_and_no_profile(env, stub):
    with pytest.raises(ValueError):
        discover.run("daily")
    with pytest.raises(RuntimeError, match="No active profile"):
        discover.run("scheduled")


def test_import_inbox_mirrors_pasted_links_into_job_list(active):
    pipeline_inbox.add([{"url": "https://job-boards.greenhouse.io/acme/jobs/12345678", "company": "Acme", "title": "AI Eng"},
                        "https://jobs.lever.co/foo/aaaa-bbbb"], "p")
    r = career_ops_scan.import_inbox("p")
    assert r["imported"] == 2 and jobs_db.count(synced=True, name="p") == 2
    j = jobs_db.list_jobs(name="p")
    acme = [x for x in j if "acme" in x["url"]][0]
    assert {x["source"] for x in j} == {"your links"} and acme["company"] == "Acme" and acme["title"] == "AI Eng"
    assert career_ops_scan.import_inbox("p")["imported"] == 0


def test_node_finder_returns_node_22_or_none():
    nb = nodeenv.node_bin()
    assert nb is None or nodeenv._major(nb) >= 22
