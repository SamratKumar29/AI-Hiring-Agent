import json

import pytest
import yaml

from brain import pipeline_inbox, profiles, sources
from tests.conftest import PREFS, RESUME
from tests.test_ingest_links import make_pdf

LINKS = """
https://www.linkedin.com/jobs/search/?keywords=ai%20engineer&location=India
https://job-boards.greenhouse.io/anthropic/jobs/4020159008
https://jobs.lever.co/acme-corp
https://acme.com/careers
https://twitter.com/someone/status/1
"""


def portals(n="p"):
    return {c["name"]: c for c in yaml.safe_load(profiles.read_file(n, "portals.yml"))["tracked_companies"]}


def test_add_classifies_routes_and_persists(active):
    r = sources.add(LINKS)
    assert r["found"] == 5 and len(r["added"]) == 5
    by = {s["type"] + ("/" + s["ats"] if s["ats"] else ""): s for s in r["added"]}
    assert by["single_posting/greenhouse"]["routed"] == "pipeline"
    assert by["company_careers/lever"]["routed"] == "portals"
    assert by["board_search"]["routed"] == "board"
    assert by["company_careers"]["routed"].startswith("unsupported")           # acme.com/careers
    assert by["unknown"]["enabled"] is False and by["unknown"]["routed"] == ""
    assert len(pipeline_inbox.pending()) == 1 and "Acme Corp" in portals()
    saved = json.loads((profiles._dir("p") / "sources.json").read_text())
    assert len(saved["sources"]) == 5


def test_add_twice_is_idempotent(active):
    sources.add(LINKS)
    r = sources.add(LINKS)
    assert r["added"] == [] and len(r["duplicates"]) == 5
    assert len(sources.list_sources()) == 5 and len(pipeline_inbox.pending()) == 1


def test_preview_does_not_save_and_flags_existing(active):
    p = sources.preview(LINKS)
    assert len(p) == 5 and not any(x["already_added"] for x in p) and sources.list_sources() == []
    sources.add("https://jobs.lever.co/acme-corp")
    assert [x["already_added"] for x in sources.preview("https://jobs.lever.co/acme-corp")] == [True]


def test_add_from_pdf_file(active, tmp_path):
    f = tmp_path / "links.pdf"
    make_pdf(f)
    r = sources.add(f)
    assert r["found"] == 4
    assert sum(s["type"] == "single_posting" for s in r["added"]) == 4        # all four are postings


def test_disable_enable_remove_follow_through(active):
    sources.add("https://job-boards.greenhouse.io/anthropic/jobs/4020159008 https://jobs.lever.co/acme-corp")
    post = sources.list_sources("single_posting")[0]
    comp = sources.list_sources("company_careers")[0]
    sources.set_enabled(post["id"], False)
    sources.set_enabled(comp["id"], False)
    assert pipeline_inbox.pending() == [] and portals()["Acme Corp"]["enabled"] is False
    sources.set_enabled(post["id"], True)
    sources.set_enabled(comp["id"], True)
    assert len(pipeline_inbox.pending()) == 1 and portals()["Acme Corp"]["enabled"] is True
    sources.remove(comp["id"])
    assert "Acme Corp" not in portals() and len(sources.list_sources()) == 1
    with pytest.raises(KeyError):
        sources.remove("nope")


def test_set_type_for_unknown_and_validation(active):
    sources.add("https://acme.com/blog/post-about-jobs-123")
    s = sources.list_sources()[0]
    assert s["type"] == "unknown" and not s["enabled"]
    s = sources.set_type(s["id"], "single_posting")
    assert s["enabled"] and s["routed"] == "pipeline"
    with pytest.raises(ValueError):
        sources.set_type(s["id"], "bogus")
    with pytest.raises(ValueError):
        sources.add("https://x.com/jobs/123456", force_type="bogus")


def test_no_route_then_sync(active):
    sources.add(LINKS, route=False)
    assert pipeline_inbox.pending() == []
    assert sources.sync()["routed"] == 4                                        # unknown stays disabled
    assert len(pipeline_inbox.pending()) == 1 and "Acme Corp" in portals()


def test_sources_are_per_profile(active):
    sources.add("https://jobs.lever.co/acme-corp")
    profiles.create_profile("q", RESUME, PREFS)
    assert sources.list_sources(name="q") == [] and len(sources.list_sources(name="p")) == 1
