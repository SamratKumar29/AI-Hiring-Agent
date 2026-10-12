import sys

from brain import jobs_db, profiles
from brain.scrapers import manual
from tests.conftest import PREFS, RESUME


def test_build_config_from_profile(active):
    c = manual.build_config("p")
    assert c["LINKEDIN_SEARCH_QUERIES"][:2] == ["AI Engineer", "ML Engineer"]       # seniority stripped
    assert c["LINKEDIN_LOCATION"] == "Bengaluru" and c["LINKEDIN_F_WT"] == 3         # hybrid
    assert c["SCRAPING_SOURCES"] == ["linkedin"] and c["LINKEDIN_GEO_ID"] == 0


def test_vague_locations_fall_back_to_city_and_any_mode_sends_no_filter(env):
    prefs = {**PREFS, "locations": ["Any", "Remote"], "work_mode": "any"}
    profiles.create_profile("v", RESUME, prefs)
    c = manual.build_config("v")
    assert c["LINKEDIN_LOCATION"] == "Bengaluru" and c["LINKEDIN_F_WT"] == 0


def test_singapore_enables_careers_future(env):
    profiles.create_profile("s", RESUME, {**PREFS, "locations": ["Singapore"], "country": "Singapore"})
    assert manual.build_config("s")["SCRAPING_SOURCES"] == ["linkedin", "careers_future"]


def test_local_db_adapter_roundtrip(active, monkeypatch):
    monkeypatch.setenv("HIRE_PROFILE", "p")
    sys.path.insert(0, str(manual.SCRAPER_DIR))
    import local_db
    local_db.save_jobs([{"job_id": "3912345678", "job_title": "AI Eng", "company": "Acme", "location": "Bengaluru",
                         "description": "d", "provider": "linkedin"},
                        {"job_id": None, "job_title": "ignored"}])
    j = jobs_db.list_jobs(name="p")
    assert len(j) == 1 and j[0]["url"] == "https://www.linkedin.com/jobs/view/3912345678" and j[0]["source"] == "linkedin"
    ids, pairs = local_db.get_existing_jobs()
    assert "3912345678" in ids and ("acme", "ai eng") in pairs
