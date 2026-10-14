import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain import digest, jobs_db, nodeenv, pipeline_inbox, rank, reports, sync_env
from brain.llm import LLMUnavailable
from tests.report_samples import TOOL_CALL, report

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def co(tmp_path, monkeypatch, active):
    """A scratch career-ops dir + a fake evaluator whose per-call behaviour is scripted by the test."""
    d = tmp_path / "scratch-career-ops"
    (d / "reports").mkdir(parents=True)
    monkeypatch.setattr(rank, "CAREER_OPS", d)
    monkeypatch.setattr(rank, "ADDITIONS", d / "batch" / "tracker-additions")
    monkeypatch.setattr(rank, "JDS_DIR", d / "jds")
    monkeypatch.setattr(rank.nodeenv, "node_bin", lambda: "node")
    monkeypatch.setattr(rank, "_fulltext", lambda url: None)
    monkeypatch.setattr(rank.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    state = SimpleNamespace(script=[], calls=[], n=0)

    def fake(cmd, cwd, timeout=900, models=None, validate=None):
        """script entries (one per job, consumed in order): list of model behaviours tried in turn:
        ("good", score) | ("bad",) | ("down",)"""
        state.calls.append((cmd[-1], models))
        behaviours = state.script.pop(0)
        errors = {}
        for i, b in enumerate(behaviours):
            m = f"model{i}"
            if b[0] == "down":
                errors[m] = "HTTP 429"
                continue
            state.n += 1
            body = report(score=b[1] if b[0] == "good" else "4", company="Zed") if b[0] == "good" else TOOL_CALL
            (d / "reports" / f"{state.n:03d}-acme-2026-10-12.md").write_text(body, encoding="utf-8")
            (d / "batch" / "tracker-additions").mkdir(parents=True, exist_ok=True)
            (d / "batch" / "tracker-additions" / f"or-{state.n:03d}-acme.tsv").write_text("1\tx\tAcme\t(see report)\tEvaluated\t\t❌\t[001]()\t\n")
            bad = validate(SimpleNamespace(returncode=0), m) if validate else None
            if bad:
                errors[m] = bad
                continue
            return SimpleNamespace(returncode=0, stdout="", stderr=""), m
        raise LLMUnavailable(errors)
    monkeypatch.setattr(sync_env, "run_with_fallback", fake)
    return SimpleNamespace(dir=d, state=state)


def queue(active, n=3, **kw):
    rows = [{"url": f"https://x.com/jobs/{400000 + i}", "title": f"Role {i}", "company": f"Co{i}", "location": "Bengaluru",
             "source": "remoteok", "description": "d" * 800, **kw} for i in range(n)]
    jobs_db.upsert_jobs(rows, name=active)
    jobs_db.mark_synced([jobs_db.job_id(r["url"]) for r in rows], active)
    pipeline_inbox.add([{"url": r["url"], "company": r["company"], "title": r["title"]} for r in rows], active)
    return [jobs_db.job_id(r["url"]) for r in rows]


def test_ranks_jobs_stores_scores_ticks_inbox_and_writes_digest(active, co):
    ids = queue(active, 2)
    co.state.script = [[("good", "4.5")], [("good", "3.8")]]
    r = rank.run(active, max_n=5, quiet=True)
    assert r["ranked"] == 2 and r["failed"] == 0 and r["remaining"] == 0
    assert all(jobs_db.get_job(i, active)["rank_score"] for i in ids)
    assert pipeline_inbox.pending(active) == []                              # both ticked off
    assert Path(r["digest"]).exists() and "Co" in Path(r["digest"]).read_text()
    tsvs = sorted((co.dir / "batch" / "tracker-additions").glob("*.tsv"))
    assert len(tsvs) == 2 and not any(t.name.startswith("or-") for t in tsvs)    # placeholder rows removed
    cols = tsvs[0].read_text().rstrip("\n").split("\t")
    assert len(cols) == 9 and cols[4] == "Evaluated" and cols[3].startswith("Role") and cols[2].startswith("Co") and "(see report)" not in cols


def test_unusable_answer_falls_through_to_next_model(active, co):
    queue(active, 1)
    co.state.script = [[("bad",), ("good", "4.0")]]
    r = rank.run(active, max_n=5, quiet=True)
    assert r["ranked"] == 1 and r["details"][0]["model"] == "model1"
    assert len(list((co.dir / "reports").glob("*.md"))) == 1                  # the junk report was deleted


def test_max_n_respected_and_remaining_reported(active, co):
    queue(active, 4)
    co.state.script = [[("good", "4.0")], [("good", "4.1")]]
    r = rank.run(active, max_n=2, quiet=True)
    assert r["ranked"] == 2 and r["remaining"] == 2 and len(co.state.calls) == 2


def test_all_models_unusable_marks_job_and_does_not_retry_it(active, co):
    ids = queue(active, 2)
    co.state.script = [[("bad",), ("bad",)], [("good", "4.0")]]
    r = rank.run(active, max_n=5, quiet=True)
    assert r["failed"] == 1 and r["ranked"] == 1
    failed = [i for i in ids if jobs_db.get_job(i, active)["rank_score"] is None][0]
    assert jobs_db.get_job(failed, active)["notes"].startswith(rank.FAILED_MARK)
    assert rank.pick(active, 10) == [] and len(rank.pick(active, 10, retry_failed=True)) == 1


def test_stops_early_when_no_model_answers(active, co):
    ids = queue(active, 5)
    co.state.script = [[("down",), ("down",)]] * 5
    r = rank.run(active, max_n=5, quiet=True)
    assert r["stopped_early"] and r["ranked"] == 0 and len(co.state.calls) == rank.MAX_CONSECUTIVE_OUTAGES
    assert all(jobs_db.get_job(i, active)["notes"] in (None, "") for i in ids)   # outage is not the job's fault


def test_working_model_is_tried_first_for_next_job(active, co):
    queue(active, 2)
    co.state.script = [[("good", "4.0")], [("good", "4.0")]]
    rank.run(active, max_n=5, quiet=True)
    assert co.state.calls[0][1] is None and co.state.calls[1][1][0] == "model0"


def test_thin_descriptions_trigger_fulltext_fetch(active, co, monkeypatch):
    jobs_db.upsert_jobs([{"url": "https://in.indeed.com/viewjob?jk=abc", "title": "T", "company": "C", "description": "short",
                          "source": "firecrawl:in.indeed.com"}], name=active)
    jid = jobs_db.job_id("https://in.indeed.com/viewjob?jk=abc")
    jobs_db.mark_synced([jid], active)
    monkeypatch.setattr(rank, "_fulltext", lambda url: "FULL POSTING TEXT " * 100)
    co.state.script = [[("good", "4.0")]]
    rank.run(active, max_n=1, quiet=True)
    assert "FULL POSTING TEXT" in jobs_db.get_job(jid, active)["description"]
    assert "FULL POSTING TEXT" in (co.dir / "jds" / f"{jid}.md").read_text()
    assert co.state.calls[0][0] == f"local:jds/{jid}.md"


def test_stale_tracker_additions_are_set_aside(active, co):
    add = co.dir / "batch" / "tracker-additions"
    add.mkdir(parents=True)
    (add / "007-old.tsv").write_text("junk")
    rank.run(active, max_n=1, quiet=True)
    assert not (add / "007-old.tsv").exists() and len(list((add / "orphaned").glob("*"))) == 1


@pytest.mark.skipif(not nodeenv.node_bin(), reason="Node >= 22 not installed")
@pytest.mark.skipif(not (rank.CAREER_OPS / "node_modules" / "js-yaml").exists(), reason="run `npm install` in career-ops first")
def test_real_merge_tracker_accepts_our_rows_and_digest_reads_them(tmp_path, active, monkeypatch):
    """Run the REAL career-ops merge-tracker on rows built by rank._tsv."""
    adds, tracker = tmp_path / "adds", tmp_path / "data" / "applications.md"
    adds.mkdir()
    tracker.parent.mkdir()
    import brain.digest as dg
    monkeypatch.setattr(dg, "tracker_path", lambda name=None: tracker)
    dg.ensure_tracker()                      # merge-tracker refuses to run without an existing file
    (tmp_path / "reports").mkdir()
    rep = reports.parse(report(score="4.2"))
    job = {"company": "Acme Corp", "title": "Senior AI Engineer"}
    (adds / "001-x.tsv").write_text(rank._tsv(1, job, rep, "001-acme-2026-10-12.md", "rank 4.3; Apply"), encoding="utf-8")
    env = {**nodeenv.env_with_node(), "CAREER_OPS_TRACKER": str(tracker), "CAREER_OPS_ADDITIONS": str(adds)}
    p = subprocess.run([nodeenv.node_bin(), "merge-tracker.mjs"], cwd=ROOT / "career-ops", env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    text = tracker.read_text(encoding="utf-8")
    assert "Acme Corp" in text and "Senior AI Engineer" in text and "4.2/5" in text and "Evaluated" in text
    # and our own reader understands what career-ops wrote
    rows = dg.read_tracker()
    assert rows[0]["company"] == "Acme Corp" and rows[0]["status"] == "Evaluated" and rows[0]["report_number"] == 1


def test_pick_prefers_pasted_links_then_title_match_then_newest(active, co):
    from brain import profiles
    profiles.update_preferences(active, {"target_roles": ["Senior AI Engineer", "ML Engineer"]})
    rows = [("https://x.com/jobs/600001", "Tech Recruiter", "2026-10-13 09:00:00", "remoteok"),
            ("https://x.com/jobs/600002", "Senior AI Engineer", "2026-10-01 09:00:00", "remoteok"),
            ("https://x.com/jobs/600003", "Machine Learning Engineer", "2026-10-02 09:00:00", "remoteok"),
            ("https://x.com/jobs/600004", "Marketing Manager", "2026-10-12 09:00:00", "your links"),
            ("https://x.com/jobs/600005", "ML Engineer", "2026-10-03 09:00:00", "remoteok")]
    jobs_db.upsert_jobs([{"url": u, "title": t, "found_at": f, "source": s, "company": "C"} for u, t, f, s in rows], name=active)
    jobs_db.mark_synced([jobs_db.job_id(r[0]) for r in rows], active)
    order = [j["title"] for j in rank.pick(active, 10)]
    assert order[0] == "Marketing Manager"                                  # the user's own link always first
    assert set(order[1:4]) == {"Senior AI Engineer", "ML Engineer", "Machine Learning Engineer"}   # relevant ones next
    assert order[1:4] == ["ML Engineer", "Machine Learning Engineer", "Senior AI Engineer"]         # ties: newest first
    assert order[-1] == "Tech Recruiter"                                    # newest, but irrelevant -> last
    assert rank.title_affinity("AI Engineer", ["Senior AI Engineer"]) > rank.title_affinity("Engineer", ["Senior AI Engineer"])
