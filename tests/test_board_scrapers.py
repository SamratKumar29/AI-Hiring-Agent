import json
from pathlib import Path

from brain.scrapers import michaelpage, remoteok, wellfound

FX = Path(__file__).parent / "fixtures"


def test_remoteok_parse_filters_by_whole_word_and_maps_fields():
    data = json.loads((FX / "remoteok.json").read_text())
    everything = remoteok.parse(data, None, 100)
    assert len(everything) >= 10 and all(r["url"].startswith("http") and r["title"] for r in everything)
    assert all(r["source"] == "remoteok" for r in everything)
    synth = [{"id": "1", "position": "Senior Analyst", "tags": ["finance"], "url": "https://remoteok.com/a", "company": "A"},
             {"id": "2", "position": "AI Engineer", "tags": ["python"], "url": "https://remoteok.com/b", "company": "B",
              "salary_min": 100000, "salary_max": 150000, "description": "<p>Build <b>LLMs</b></p>"},
             {"id": "3", "position": "Plumber", "tags": ["machine learning"], "url": "https://remoteok.com/c", "company": "C"}]
    got = remoteok.parse(synth, remoteok.keywords_from_roles(["AI Engineer", "Machine Learning Engineer"]))
    assert [r["company"] for r in got] == ["B", "C"]                    # "ai" must NOT match inside "Analyst"
    assert got[0]["salary_min"] == 100000 and got[0]["salary_text"] == "$100,000 - $150,000"
    assert got[0]["description"] == "Build\nLLMs" or "LLMs" in got[0]["description"]
    assert remoteok.parse(synth, ["ai"], limit=1)[0]["company"] == "B"


def test_michaelpage_parse_fixture():
    rows = michaelpage.parse((FX / "michaelpage.html").read_text(), "https://www.michaelpage.co.in/jobs/technology")
    assert len(rows) == 4
    r = rows[0]
    assert r["url"].startswith("https://www.michaelpage.co.in/job-detail/") and r["title"] and r["location"]
    assert r["source"] == "michaelpage" and len(r["description"]) > 30


def test_wellfound_parse_fixture():
    rows = wellfound.parse((FX / "wellfound.html").read_text())
    assert len(rows) >= 2
    assert all(r["url"].startswith("https://wellfound.com/jobs/") and r["company"] and r["title"] for r in rows)
    with_salary = [r for r in rows if r["salary_text"]]
    assert with_salary and with_salary[0]["salary_min"] and with_salary[0]["salary_min"] >= 500_000   # INR lakhs


def test_garbage_input_gives_empty_not_crash():
    assert michaelpage.parse("<html></html>") == [] and wellfound.parse("") == []
    assert remoteok.parse([{"legal": "x"}, "junk", None]) == []


def test_fetch_wrappers_skip_foreign_urls_and_survive_errors(monkeypatch):
    from brain.scrapers import _http
    monkeypatch.setattr(_http, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert michaelpage.fetch(["https://example.com/x"]) == [] and michaelpage.fetch(["https://www.michaelpage.co.in/x"]) == []
    assert wellfound.fetch(["https://example.com/x"]) == [] and wellfound.fetch(["https://wellfound.com/x"]) == []
