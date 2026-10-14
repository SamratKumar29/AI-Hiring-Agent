import pytest

from brain import digest, jobs_db, profiles, reports
from tests.report_samples import report

PREFS = {"currency": "INR", "min_base_salary": 2_000_000, "preferred_salary": 3_000_000, "work_mode": "remote"}


def rep(**kw):
    return reports.parse(report(**kw))


def test_blend_adjustments_are_explained():
    s, why = digest.blend({"location": "Remote"}, rep(), PREFS)
    assert s == pytest.approx(4.2 + 0.2 + 0.1)                       # pay reaches preferred + remote
    assert any("preferred" in w for w in why) and any("remote" in w for w in why)
    low = rep()
    low["advertised_comp"] = "Rs 5-8 LPA"
    s, why = digest.blend({}, low, PREFS)
    assert s == pytest.approx(3.7) and "below your minimum" in why[0]


def test_blend_penalties_and_clamp():
    r = rep(legit="Suspicious")
    r.update(hard_stops=["needs visa", "onsite only", "third"], risk_level="High", confidence="Low", final_decision="Skip",
             advertised_comp=None)
    s, why = digest.blend({}, r, {})
    assert s == pytest.approx(4.2 - 0.7 - 1.0 - 0.3 - 0.1 - 0.5) and len(why) == 5
    assert digest.blend({}, {"score": 1.0, "hard_stops": ["a", "b"], "legitimacy": "Suspicious"}, {})[0] == 0.0
    assert digest.blend({}, {"score": 5.0, "advertised_comp": "Rs 99 LPA"}, PREFS)[0] == 5.0


def test_chance():
    assert digest.chance(rep()) == "High"
    assert digest.chance({**rep(), "hard_stops": ["x"]}) == "Low"
    assert digest.chance({**rep(), "final_decision": "Consider", "confidence": "Medium"}) == "Medium"
    assert digest.chance({**rep(), "score": 2.5}) == "Low"


def seed(active, tmp_path, n=3, scores=("4.6", "3.9", "4.2")):
    out = []
    for i in range(n):
        jobs_db.upsert_jobs([{"url": f"https://x.com/jobs/{200000 + i}", "title": f"Role {i}", "company": f"Co{i}",
                              "location": "Bengaluru", "source": "remoteok"}], name=active)
        jid = jobs_db.job_id(f"https://x.com/jobs/{200000 + i}")
        f = profiles.workspace_path(active, "reports") / f"{i + 1:03d}-co{i}-2026-10-12.md"
        f.write_text(report(score=scores[i], company=f"Co{i}"), encoding="utf-8")
        assert digest.rank_job(jid, f, active)
        out.append(jid)
    return out


def test_rank_job_rejects_garbage_and_stores_score(active, tmp_path):
    jobs_db.upsert_jobs([{"url": "https://x.com/jobs/300000", "title": "T"}], name=active)
    jid = jobs_db.job_id("https://x.com/jobs/300000")
    bad = tmp_path / "001-bad.md"
    bad.write_text("<function>nope</function>")
    assert digest.rank_job(jid, bad, active) is None and jobs_db.get_job(jid, active)["rank_score"] is None


def test_top_orders_filters_and_writes_digest(active, tmp_path):
    ids = seed(active, tmp_path)
    top = digest.top(10, active)
    assert [t["company"] for t in top] == ["Co0", "Co2", "Co1"] and [t["rank"] for t in top] == [1, 2, 3]
    assert top[0]["chance"] == "High" and top[0]["career_ops_score"] == 4.6 and top[0]["top_strengths"] == ["RAG"]
    jobs_db.set_decision(ids[0], "dismissed", name=active)
    assert [t["company"] for t in digest.top(10, active)] == ["Co2", "Co1"]       # dismissed hidden by default
    assert len(digest.top(10, active, decision="dismissed")) == 1
    assert len(digest.top(1, active)) == 1
    path, items = digest.write_digest(5, active)
    text = path.read_text()
    assert path.parent.name == "digests" and "| 1 |" in text and "Co2" in text and "[open](https://x.com/jobs/" in text
    assert digest.latest_digest(active) == path


def tracker(active, rows):
    head = "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n|---|---|---|---|---|---|---|---|---|\n"
    body = "".join(f"| {n} | 2026-10-12 | C | R | 4.0/5 | {st} | ❌ | [{n:03d}](reports/{n:03d}-co{n - 1}-2026-10-12.md) | |\n" for n, st in rows)
    digest.tracker_path(active).write_text(head + body, encoding="utf-8")


def test_read_tracker_and_sync_furthest_stage_wins(active, tmp_path):
    ids = seed(active, tmp_path)
    jobs_db.set_decision(ids[1], "applied", name=active)                    # UI says applied; tracker still Evaluated
    tracker(active, [(1, "Interview"), (2, "Evaluated"), (3, "Evaluated")])  # tracker advanced job 1 on its own
    assert [r["status"] for r in digest.read_tracker(active)] == ["Interview", "Evaluated", "Evaluated"]
    res = digest.sync_status(active)
    assert res == {"to_db": 1, "to_tracker": 1}
    assert jobs_db.get_job(ids[0], active)["decision"] == "interview"
    assert {r["report_number"]: r["status"] for r in digest.read_tracker(active)}[2] == "Applied"
    assert digest.sync_status(active) == {"to_db": 0, "to_tracker": 0}      # stable


def test_sync_negative_outcomes_win_and_liked_is_kept(active, tmp_path):
    ids = seed(active, tmp_path)
    jobs_db.set_decision(ids[0], "liked", name=active)
    jobs_db.set_decision(ids[1], "dismissed", name=active)
    tracker(active, [(1, "Evaluated"), (2, "Applied"), (3, "Rejected")])
    digest.sync_status(active)
    assert jobs_db.get_job(ids[0], active)["decision"] == "liked"            # Evaluated == liked, untouched
    assert jobs_db.get_job(ids[1], active)["decision"] == "dismissed"        # dismissal beats tracker's Applied
    assert jobs_db.get_job(ids[2], active)["decision"] == "rejected"         # rejection recorded in tracker flows to db
    assert {r["report_number"]: r["status"] for r in digest.read_tracker(active)}[2] == "SKIP"


def test_sync_without_tracker_is_a_noop(active):
    assert digest.sync_status(active) == {"to_db": 0, "to_tracker": 0}
