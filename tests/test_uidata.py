import json
import zipfile

import pytest

from brain import jobs_db, uidata


def test_board_urls():
    assert uidata.board_search_url("linkedin", "AI Engineer", "Bengaluru") == "https://www.linkedin.com/jobs/search/?keywords=AI+Engineer&location=Bengaluru"
    assert uidata.board_search_url("naukri", "AI Engineer", "Bengaluru") == "https://www.naukri.com/ai-engineer-jobs-in-bengaluru"
    assert "remoteok.com/remote-ai-engineer-jobs" in uidata.board_search_url("remoteok", "AI Engineer")
    with pytest.raises(ValueError):
        uidata.board_search_url("linkedin", " ")
    with pytest.raises(ValueError):
        uidata.board_search_url("nope", "x")
    for b in uidata.BOARD_FORMS:
        assert uidata.board_search_url(b, "ml engineer", "pune").startswith("https://")


def test_board_urls_are_recognised_by_the_classifier():
    from brain.ingest_links import classify
    for b in ("linkedin", "indeed", "naukri", "wellfound", "remoteok"):
        assert classify(uidata.board_search_url(b, "ai engineer", "bengaluru"))["type"] == "board_search", b


def test_keyword_match():
    r = uidata.keyword_match("We need Python, Kubernetes and Terraform. Python is key.", "I know Python and Docker")
    assert "python" in r["found"] and "kubernetes" in r["missing"] and "terraform" in r["missing"]


def test_kpis_and_attention(active, monkeypatch):
    jobs_db.upsert_jobs([{"title": "T", "company": "C", "url": "https://x.com/a1", "description": "d"}], active)
    k = uidata.kpis(active)
    assert k["total"] == 1 and k["waiting"] == 1 and k["liked"] == 0
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    items = uidata.needs_attention(active)
    assert any("key" in i["text"] for i in items) and any("waiting" in i["text"] for i in items)
    assert uidata.needs_attention(None)[-1]["page"] == "Profiles"


def test_export_import_roundtrip(active, tmp_path):
    z = uidata.export_profile(active, tmp_path / "p.zip")
    assert zipfile.is_zipfile(z)
    name = uidata.import_profile(z, "copy1")
    assert name == "copy1"
    with pytest.raises(FileExistsError):
        uidata.import_profile(z, "copy1")


def test_import_rejects_bad_zip(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("x/readme.txt", "hi")
    with pytest.raises(ValueError):
        uidata.import_profile(z)
    z2 = tmp_path / "evil.zip"
    with zipfile.ZipFile(z2, "w") as f:
        f.writestr("p/preferences.json", "{}")
        f.writestr("p/../../evil.txt", "x")
    with pytest.raises(ValueError):
        uidata.import_profile(z2)


def test_resumes_for_job_lists_pdfs(active):
    from brain import tailor
    d = tailor.out_dir("abc", active)
    (d / "career-ops.pdf").write_bytes(b"%PDF-1.4 x")
    (d / "note.txt").write_text("x")
    rows = uidata.resumes_for_job("abc", active)
    assert [r["engine"] for r in rows] == ["career-ops"]


def test_followups_due_never_raises(active):
    assert isinstance(uidata.followups_due(active), list)


def test_form_to_prefs_matches_questionnaire_rules():
    from brain import profiles
    prefs, bad = profiles.form_to_prefs({"full_name": "A B", "target_roles": "AI Engineer, ML Engineer", "min_base_salary": "25 LPA",
                                          "needs_sponsorship": True, "work_mode": "Hybrid", "notice_period_days": "45"})
    assert not bad
    assert prefs["target_roles"] == ["AI Engineer", "ML Engineer"] and prefs["min_base_salary"] == 2500000
    assert prefs["min_base_salary_text"] == "25 LPA" and prefs["needs_sponsorship"] is True
    assert prefs["work_mode"] == "hybrid" and prefs["notice_period_days"] == 45


def test_form_to_prefs_reports_problems():
    from brain import profiles
    prefs, bad = profiles.form_to_prefs({"target_roles": "", "min_base_salary": "lots", "work_mode": "sometimes", "years_experience": "x"})
    assert len(bad) == 4 and prefs["work_mode"] == "any"
