import pytest
import yaml

from brain import portals_edit as pe, profiles


def tracked(name="p"):
    return yaml.safe_load(profiles.read_file(name, "portals.yml"))["tracked_companies"]


def test_adds_new_company_keeps_comments_and_valid_yaml(active):
    before = profiles.read_file("p", "portals.yml")
    r = pe.add_companies([{"name": "Gitlab", "careers_url": "https://boards.greenhouse.io/gitlab/", "ats": "greenhouse"}])
    assert r["added"] == ["Gitlab"]
    after = profiles.read_file("p", "portals.yml")
    assert after.count("\n#") >= before.count("\n#")                                  # comments intact
    g = [c for c in tracked() if c["name"] == "Gitlab"]
    assert g and g[0]["careers_url"] == "https://boards.greenhouse.io/gitlab" and g[0]["enabled"] is True


def test_duplicates_by_url_or_name_and_unsupported(active):
    e = {"name": "Gitlab", "careers_url": "https://boards.greenhouse.io/gitlab", "ats": "greenhouse"}
    pe.add_companies([e])
    r = pe.add_companies([e, {"name": "gitlab", "careers_url": "https://jobs.lever.co/gitlab", "ats": "lever"},
                          {"name": "Acme", "careers_url": "https://acme.com/careers", "ats": None}])
    assert r["added"] == [] and len(r["duplicates"]) == 2 and r["unsupported"] == ["https://acme.com/careers"]
    assert sum(c["name"].lower() == "gitlab" for c in tracked()) == 1


def test_second_batch_goes_under_same_marker(active):
    pe.add_companies([{"name": "A1", "careers_url": "https://jobs.lever.co/a1", "ats": "lever"}])
    pe.add_companies([{"name": "B1", "careers_url": "https://jobs.lever.co/b1", "ats": "lever"}])
    assert profiles.read_file("p", "portals.yml").count("Added from your sources") == 1
    assert {"A1", "B1"} <= {c["name"] for c in tracked()}


def test_name_needing_quotes(active):
    pe.add_companies([{"name": "Foo: The Bar #1", "careers_url": "https://jobs.lever.co/foo", "ats": "lever"}])
    assert "Foo: The Bar #1" in [c["name"] for c in tracked()]


def test_toggle_and_remove(active):
    pe.add_companies([{"name": "A1", "careers_url": "https://jobs.lever.co/a1", "ats": "lever"},
                      {"name": "B1", "careers_url": "https://jobs.lever.co/b1", "ats": "lever"}])
    assert pe.set_company_enabled("https://jobs.lever.co/a1", False)
    d = {c["name"]: c for c in tracked()}
    assert d["A1"]["enabled"] is False and d["B1"]["enabled"] is True
    assert pe.set_company_enabled("https://jobs.lever.co/a1/", True) and {c["name"]: c for c in tracked()}["A1"]["enabled"]
    assert pe.remove_company("https://jobs.lever.co/a1") is True
    assert "A1" not in {c["name"] for c in tracked()} and "B1" in {c["name"] for c in tracked()}
    assert pe.remove_company("https://nope.com") is False


def test_missing_section_is_clear_error(active):
    profiles.write_file("p", "portals.yml", "title_filter:\n  positive: [x]\n")
    with pytest.raises(RuntimeError, match="tracked_companies"):
        pe.add_companies([{"name": "A", "careers_url": "https://jobs.lever.co/a", "ats": "lever"}])
