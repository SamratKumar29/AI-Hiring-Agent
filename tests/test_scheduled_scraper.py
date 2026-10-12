import sys

from brain import jobs_db, profiles, sources
from brain.scrapers import scheduled
from tests.conftest import PREFS, RESUME


def test_queries_use_board_search_sources_and_profile_roles(active):
    sources.add("https://www.linkedin.com/jobs/search/?keywords=ai https://in.indeed.com/jobs?q=ai https://wellfound.com/role/l/ml/india")
    q = scheduled.build_queries("p")
    assert [x.split()[0] for x in q] == ["site:linkedin.com", "site:in.indeed.com", "site:wellfound.com"]
    assert '"AI Engineer"' in q[0] and "Bengaluru" in q[0]


def test_queries_fall_back_to_default_boards(active):
    q = scheduled.build_queries("p")
    assert len(q) >= 3 and all(x.startswith("site:") for x in q)


def test_skipped_without_firecrawl_key(active, monkeypatch):
    monkeypatch.setattr(scheduled.config, "get", lambda k, d="": "" if k == "FIRECRAWL_API_KEY" else d)
    r = scheduled.run("p")
    assert r["skipped"] and not r["ok"] and "FIRECRAWL_API_KEY" in r["reason"]


def test_run_saves_scraped_jobs_and_hides_key_in_errors(active, monkeypatch):
    monkeypatch.setattr(scheduled.config, "get", lambda k, d="": "fc-SECRET" if k == "FIRECRAWL_API_KEY" else d)
    sys.path.insert(0, str(scheduled.AGENT_DIR))
    import agent
    monkeypatch.setattr(agent, "scrape_jobs", lambda q: [
        {"title": "AI Eng", "company": "Acme", "url": "https://www.indeed.com/viewjob?jk=1", "location": "Pune", "description": "d"},
        {"title": "no url", "company": "X", "url": ""}])
    r = scheduled.run("p")
    assert r["ok"] and r["found"] == 2 and r["added"] == 1
    assert jobs_db.list_jobs(name="p")[0]["source"] == "firecrawl:indeed.com"
    monkeypatch.setattr(agent, "scrape_jobs", lambda q: (_ for _ in ()).throw(RuntimeError("401 key fc-SECRET bad")))
    r = scheduled.run("p")
    assert not r["ok"] and "fc-SECRET" not in r["reason"]
