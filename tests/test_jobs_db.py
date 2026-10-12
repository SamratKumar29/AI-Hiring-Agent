import pytest

from brain import jobs_db as db, profiles
from tests.conftest import PREFS, RESUME


def J(i, **kw):
    return {"url": f"https://x.com/jobs/{i}", "title": f"Eng {i}", "company": f"Co{i}", "source": "t", **kw}


def test_upsert_twice_one_row_and_url_variants(active):
    r = db.upsert_jobs([J(111111), J(111111, title="other")])
    assert r["inserted"] == 1 and db.count() == 1
    r = db.upsert_jobs([{"url": "https://x.com/jobs/111111/?utm_source=a", "title": "zzz"}])
    assert r["inserted"] == 0 and db.count() == 1
    assert db.upsert_jobs([{"url": "nope"}, {"title": "no url"}])["skipped"] == 2


def test_upsert_fills_blanks_but_keeps_user_state(active):
    db.upsert_jobs([J(1000001, location="")])
    jid = db.job_id("https://x.com/jobs/1000001")
    db.set_decision(jid, "liked", "great")
    db.set_rank(jid, 4.2, "reports/001.md")
    r = db.upsert_jobs([J(1000001, location="Bengaluru", title="CHANGED", description="d")])
    j = db.get_job(jid)
    assert r["updated"] == 1 and j["location"] == "Bengaluru" and j["description"] == "d"
    assert j["title"] == "Eng 1000001" and j["decision"] == "liked" and j["rank_score"] == 4.2 and j["notes"] == "great"


def test_decisions_history_and_validation(active):
    db.upsert_jobs([J(2000001)])
    jid = db.job_id("https://x.com/jobs/2000001")
    db.set_decision(jid, "liked")
    db.set_decision(jid, "applied", "sent")
    j = db.get_job(jid)
    assert j["decision"] == "applied" and j["notes"] == "sent" and j["decided_at"]
    assert [h["decision"] for h in db.history(jid)] == ["liked", "applied"]
    with pytest.raises(ValueError):
        db.set_decision(jid, "bogus")
    with pytest.raises(KeyError):
        db.set_decision("missing", "liked")


def test_filters_order_and_pagination(active):
    db.upsert_jobs([J(3000001, salary_min=2_000_000, source="a", description="python llm"),
                    J(3000002, salary_min=4_000_000, source="b"), J(3000003, source="a", company="Acme")])
    ids = [db.job_id(f"https://x.com/jobs/{3000000 + i}") for i in (1, 2, 3)]
    db.set_rank(ids[0], 3.0)
    db.set_rank(ids[1], 4.5)
    db.set_decision(ids[2], "dismissed")
    assert [j["job_id"] for j in db.list_jobs()] == [ids[1], ids[0], ids[2]]       # unranked last
    assert db.count(decision="dismissed") == 1 and db.count(decision=["new", "dismissed"]) == 3
    assert db.count(min_score=4) == 1 and db.count(source="a") == 2
    assert db.count(min_salary=3_000_000) == 1 and db.count(text="llm") == 1 and db.count(text="acme") == 1
    assert [j["job_id"] for j in db.list_jobs(order="salary desc")][0] == ids[1]
    assert len(db.list_jobs(limit=1, offset=1)) == 1
    with pytest.raises(ValueError):
        db.list_jobs(order="1; drop table jobs")


def test_sql_injection_in_text_filter_is_inert(active):
    db.upsert_jobs([J(4000001)])
    assert db.count(text="'; DROP TABLE jobs; --") == 0 and db.count() == 1


def test_unsynced_and_mark_synced(active):
    db.upsert_jobs([J(5000001), J(5000002)])
    ids = [j["job_id"] for j in db.unsynced()]
    assert len(ids) == 2
    db.set_decision(ids[0], "dismissed")
    assert [j["job_id"] for j in db.unsynced()] == [ids[1]]
    assert db.mark_synced(ids[1:]) == 1 and db.unsynced() == []


def test_stats(active):
    db.upsert_jobs([J(6000001, source="a"), J(6000002, source="b")])
    s = db.stats()
    assert s["total"] == 2 and s["by_decision"] == {"new": 2} and s["by_source"] == {"a": 1, "b": 1} and s["unsynced"] == 2


def test_profiles_have_separate_databases(active):
    profiles.create_profile("q", RESUME, PREFS)
    db.upsert_jobs([J(7000001)], name="p")
    assert db.count(name="p") == 1 and db.count(name="q") == 0
    assert db.db_path("p") != db.db_path("q")


def test_indeed_and_linkedin_tracking_urls_collapse(active):
    a = "https://in.indeed.com/rc/clk?jk=cdaaed441be70bcc&bb=TOKEN1&xkcr=a"
    b = "https://in.indeed.com/rc/clk?jk=cdaaed441be70bcc&bb=TOKEN2"
    db.upsert_jobs([{"url": a, "title": "AI Eng"}])
    r = db.upsert_jobs([{"url": b, "title": "AI Eng"}, {"url": "https://www.linkedin.com/jobs/view/ai-eng-3912345678?trk=x"}])
    assert r["inserted"] == 1 and db.count() == 2
    assert db.get_job(db.job_id(a))["url"] == "https://in.indeed.com/viewjob?jk=cdaaed441be70bcc"
    assert db.job_id(a) == db.job_id(b)
