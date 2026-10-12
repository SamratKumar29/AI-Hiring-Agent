from brain import jobs_db, pipeline_inbox, profiles, sync_pipeline


def J(i, **kw):
    return {"url": f"https://x.com/jobs/{100000 + i}", "title": f"Role {i}", "company": f"Co{i}", "source": "remoteok", **kw}


def test_adds_to_inbox_marks_synced_and_is_idempotent(active, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pipeline, "JDS_DIR", tmp_path / "jds")
    jobs_db.upsert_jobs([J(1), J(2)], name="p")
    r = sync_pipeline.run("p")
    assert r["added"] == 2 and r["considered"] == 2
    assert pipeline_inbox.pending("p") == ["- [ ] https://x.com/jobs/100001 | Co1 | Role 1",
                                           "- [ ] https://x.com/jobs/100002 | Co2 | Role 2"]
    assert jobs_db.count(synced=True, name="p") == 2
    assert sync_pipeline.run("p")["added"] == 0 and len(pipeline_inbox.pending("p")) == 2


def test_filtered_jobs_never_reach_the_inbox(active, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pipeline, "JDS_DIR", tmp_path / "jds")
    profiles.update_preferences("p", {"min_base_salary": 5_000_000, "currency": "INR", "locations": ["Any"]})
    jobs_db.upsert_jobs([J(1, salary_text="₹5L"), J(2, salary_text="₹60L")], name="p")
    r = sync_pipeline.run("p")
    assert r["filtered_out"] == 1 and r["added"] == 1 and r["by_reason"] == {"below_salary": 1}
    assert len(pipeline_inbox.pending("p")) == 1
    assert jobs_db.count(decision="dismissed", name="p") == 1


def test_local_jd_for_linkedin_style_sources(active, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pipeline, "JDS_DIR", tmp_path / "jds")
    long_desc = "We build LLM products. " * 20
    jobs_db.upsert_jobs([J(1, source="linkedin", description=long_desc, location="Bengaluru"),
                         J(2, source="linkedin", description="short"),
                         J(3, source="remoteok", description=long_desc)], name="p")
    r = sync_pipeline.run("p")
    jid = jobs_db.job_id("https://x.com/jobs/100001")
    assert r["local_jds"] == 1
    lines = pipeline_inbox.pending("p")
    assert lines[0] == f"- [ ] local:jds/{jid}.md | Co1 | Role 1"
    assert lines[1].startswith("- [ ] https://x.com/jobs/100002") and lines[2].startswith("- [ ] https://x.com/jobs/100003")
    text = (tmp_path / "jds" / f"{jid}.md").read_text()
    assert "**URL:** https://x.com/jobs/100001" in text and "**Location:** Bengaluru" in text and "LLM products" in text


def test_limit_and_already_queued_urls(active, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_pipeline, "JDS_DIR", tmp_path / "jds")
    pipeline_inbox.add(["https://x.com/jobs/100001"], "p")                     # user pasted it earlier
    jobs_db.upsert_jobs([J(1), J(2), J(3)], name="p")
    r = sync_pipeline.run("p", limit=2)
    assert r["considered"] == 2 and r["already_in_pipeline"] == 1 and r["added"] == 1
    assert jobs_db.count(synced=False, decision="new", name="p") == 1          # the 3rd waits for the next run
    assert sync_pipeline.run("p")["added"] == 1
