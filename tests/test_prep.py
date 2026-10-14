import pytest

from brain import digest, jobs_db, llm, prep, profiles
from tests.report_samples import report

GOOD = "# Cover letter\n\nDear hiring team at Acme, " + "I built production RAG systems. " * 20


@pytest.fixture
def job(active, monkeypatch):
    monkeypatch.setattr("brain.rank._fulltext", lambda url: None)
    jobs_db.upsert_jobs([{"url": "https://x.com/jobs/700001", "title": "AI Engineer", "company": "Acme", "location": "Bengaluru",
                          "description": "We need RAG and LangGraph experience. " * 30, "source": "t"}], name=active)
    jid = jobs_db.job_id("https://x.com/jobs/700001")
    f = profiles.workspace_path(active, "reports") / "007-acme-2026-10-13.md"
    f.write_text(report(score="4.4", company="Acme"), encoding="utf-8")
    digest.rank_job(jid, f, active)
    return jid


@pytest.fixture
def fake_llm(monkeypatch):
    log = {"calls": []}

    def chat(messages, model=None, max_tokens=512, timeout=60, backoff=1.0, validate=None):
        log["calls"].append({"messages": messages, "max_tokens": max_tokens})
        text = log.get("reply", GOOD)
        bad = validate(text) if validate else None
        if bad:
            raise llm.LLMUnavailable({"m": f"unusable: {bad}"})
        return text, "test/model"
    monkeypatch.setattr(llm, "chat", chat)
    return log


@pytest.mark.parametrize("kind", list(prep.KINDS))
def test_every_kind_produces_a_file_with_the_right_inputs(active, job, fake_llm, kind):
    r = prep.generate(job, kind)
    assert r["ok"] and r["model"] == "test/model" and r["path"].endswith(f"/prep/{job}/{kind}.md")
    sys_msg, user_msg = (m["content"] for m in fake_llm["calls"][0]["messages"])
    assert "NO tools" in sys_msg and "=== CANDIDATE CV ===" in sys_msg
    assert (prep.MODES / prep.KINDS[kind]["mode"]).read_text()[:60] in sys_msg                     # the real mode prompt
    assert "Company: Acme" in user_msg and "Role: AI Engineer" in user_msg and "https://x.com/jobs/700001" in user_msg
    assert "Archetype" in user_msg and "RAG and LangGraph" in user_msg                           # report + job description
    assert prep.read(job, kind) == r["text"] and prep.list_prep(job)[kind] == r["path"]


def test_cv_and_profile_come_from_the_active_profile(active, job, fake_llm):
    profiles.write_file(active, "cv.md", "# UNIQUE-CV-MARKER-123\nBuilt things.")
    prep.generate(job, "cover")
    assert "UNIQUE-CV-MARKER-123" in fake_llm["calls"][0]["messages"][0]["content"]


def test_offer_letter_text_is_passed_through(active, job, fake_llm):
    prep.generate(job, "offer", extra="Base salary 28 LPA, 3-month notice, non-compete 12 months")
    assert "non-compete 12 months" in fake_llm["calls"][0]["messages"][1]["content"]
    prep.generate(job, "offer")
    assert "EXTRA INPUT" not in fake_llm["calls"][1]["messages"][1]["content"]
    assert "pre-offer negotiation brief" in fake_llm["calls"][1]["messages"][1]["content"]


def test_tool_call_or_tiny_answers_are_rejected_and_nothing_is_written(active, job, fake_llm):
    for bad in ("<tool_call><function=bash>ls</function></tool_call>" + "x" * 400, "ok", "   "):
        fake_llm["reply"] = bad
        r = prep.generate(job, "cover")
        assert not r["ok"] and "unusable" in r["error"] and r["path"] is None
    assert prep.read(job, "cover") is None


def test_regeneration_and_edits_keep_history(active, job, fake_llm):
    prep.generate(job, "cover")
    fake_llm["reply"] = GOOD.replace("Dear", "Hello")
    prep.generate(job, "cover")
    hist = list((prep.folder(job) / "history").glob("cover-*.md"))
    assert len(hist) == 1 and "Dear hiring team" in hist[0].read_text()
    assert prep.read(job, "cover").startswith("# Cover letter\n\nHello")
    prep.save_edit(job, "cover", "My own edited letter")
    assert prep.read(job, "cover") == "My own edited letter\n"
    assert len(list((prep.folder(job) / "history").glob("cover-*.md"))) >= 1


def test_code_fences_are_stripped(active, job, fake_llm):
    fake_llm["reply"] = "```markdown\n" + GOOD + "\n```"
    assert prep.generate(job, "cover")["text"].startswith("# Cover letter") and "```" not in prep.read(job, "cover")


def test_unknown_kind_and_job(active, job, fake_llm):
    with pytest.raises(ValueError):
        prep.generate(job, "poem")
    with pytest.raises(KeyError):
        prep.generate("nope", "cover")


def test_all_models_failing_is_reported_not_raised(active, job, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable({"m1": "HTTP 429", "m2": "timeout"})))
    r = prep.generate(job, "interview")
    assert not r["ok"] and "m1: HTTP 429" in r["error"]


def test_thin_description_is_enriched_first(active, job, fake_llm, monkeypatch):
    jobs_db.update_fields(job, active, description="short teaser")
    monkeypatch.setattr("brain.rank._fulltext", lambda url: "FULL POSTING " * 100)
    prep.generate(job, "cover")
    assert "FULL POSTING" in fake_llm["calls"][0]["messages"][1]["content"]
    assert "FULL POSTING" in jobs_db.get_job(job, active)["description"]


def test_mark_applied_updates_db_and_tracker(active, job):
    digest.ensure_tracker(active)
    digest.tracker_path(active).write_text(digest.TRACKER_HEADER + "| 7 | 2026-10-13 | Acme | AI Engineer | 4.4/5 | Evaluated | ❌ | [007](../reports/007-acme-2026-10-13.md) | |\n")
    r = prep.mark_applied(job, notes="applied on company site")
    assert r["job"]["decision"] == "applied" and r["sync"]["to_tracker"] == 1
    assert digest.read_tracker(active)[0]["status"] == "Applied"


def test_resolve_by_report_number_id_url(active, job):
    assert prep.resolve("7")["job_id"] == job and prep.resolve("007")["job_id"] == job
    assert prep.resolve(job)["job_id"] == job and prep.resolve("https://x.com/jobs/700001")["job_id"] == job
    with pytest.raises(prep.PrepError, match="report number 9"):
        prep.resolve("9")
    with pytest.raises(prep.PrepError):
        prep.resolve("gibberish")


def test_validate_rejects_refusals():
    from brain import prep
    assert prep.validate("I can't write the letter yet - the workflow has mandatory gates. " + "x" * 800)
    assert prep.validate("Dear Hiring Team,\n\n" + "I am applying for the role. " * 40) is None


def test_validate_rejects_confirmation_gate():
    from brain import prep
    t = "Here\u2019s what I found about Siemens:\n\nI couldn\u2019t find useful recent context. Can you share what you know?\n" + "kw " * 400
    assert prep.validate(t)
