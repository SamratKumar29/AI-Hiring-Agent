import threading

import pytest

from brain import pipeline_inbox as pi


def test_creates_skeleton_and_adds_once(active):
    r1 = pi.add(["https://job-boards.greenhouse.io/anthropic/jobs/4020159008"])
    r2 = pi.add(["https://job-boards.greenhouse.io/anthropic/jobs/4020159008?utm_source=x"])
    assert len(r1["added"]) == 1 and r2["added"] == [] and len(r2["duplicates"]) == 1
    text = pi.inbox_path().read_text()
    assert text.count("4020159008") == 1 and "## Pending" in text and "## Processed" in text
    assert pi.pending() == ["- [ ] https://job-boards.greenhouse.io/anthropic/jobs/4020159008"]


def test_company_title_format_and_sanitising(active):
    pi.add([{"url": "https://jobs.lever.co/acme/aaaa", "company": "Ac|me\nInc", "title": "Sr AI Eng"}])
    pi.add([{"url": "https://jobs.lever.co/acme/bbbb", "company": "Acme"}])
    assert pi.pending() == ["- [ ] https://jobs.lever.co/acme/aaaa | Ac me Inc | Sr AI Eng",
                            "- [ ] https://jobs.lever.co/acme/bbbb | Acme | N/A"]


def test_inserted_before_processed_and_existing_text_kept(active):
    p = pi.inbox_path()
    p.write_text("# Pipeline\n\n## Pending\n\n- [ ] https://a.com/jobs/111111 | A | X\n\n## Processed\n\n- [x] #001 | https://done.com/jobs/222222 | D | Y | 4.0/5\n")
    r = pi.add(["https://b.com/jobs/333333", "https://done.com/jobs/222222", "not a url", "https://a.com/jobs/111111/"])
    assert r["added"] == ["https://b.com/jobs/333333"] and len(r["duplicates"]) == 2 and r["invalid"] == ["not a url"]
    t = p.read_text()
    assert t.index("b.com") < t.index("## Processed") and "#001 | https://done.com" in t
    assert not (p.parent / "pipeline.md.lock").exists()


def test_missing_pending_header_is_created(active):
    pi.inbox_path().write_text("# Pipeline\n\n## Processed\n\n")
    pi.add(["https://b.com/jobs/333333"])
    t = pi.inbox_path().read_text()
    assert t.index("## Pending") < t.index("b.com") < t.index("## Processed")


def test_dedupes_against_scan_history(active):
    hist = pi.inbox_path().parent / "scan-history.tsv"
    hist.write_text("url\tfirst_seen\tportal\ttitle\tcompany\tstatus\nhttps://seen.com/jobs/999999\t2026-01-01\tx\tt\tc\tadded\n")
    r = pi.add(["https://seen.com/jobs/999999"])
    assert r["added"] == [] and len(r["duplicates"]) == 1


def test_linkedin_variants_dedupe(active):
    pi.add(["https://www.linkedin.com/jobs/view/ai-engineer-3912345678?trk=a"])
    r = pi.add(["https://in.linkedin.com/jobs/collections/x/?currentJobId=3912345678"])
    assert r["added"] == [] and pi.pending() == ["- [ ] https://www.linkedin.com/jobs/view/3912345678"]


def test_remove_pending(active):
    pi.add(["https://b.com/jobs/333333", "https://c.com/jobs/444444"])
    assert pi.remove_pending("https://b.com/jobs/333333/") is True
    assert pi.remove_pending("https://nope.com/x") is False
    assert pi.pending() == ["- [ ] https://c.com/jobs/444444"]


def test_stale_lock_is_broken_and_live_lock_times_out(active, monkeypatch):
    import os, time
    p = pi.inbox_path()
    lock = type(p)(str(p) + ".lock")
    lock.mkdir()
    old = time.time() - 120
    os.utime(lock, (old, old))
    assert pi.add(["https://b.com/jobs/333333"])["added"]               # stale lock removed
    lock.mkdir()
    monkeypatch.setattr(pi, "TIMEOUT_S", 0.3)
    with pytest.raises(TimeoutError):
        pi.add(["https://c.com/jobs/444444"])


def test_parallel_adds_lose_nothing(active):
    urls = [f"https://x.com/jobs/{100000 + i}" for i in range(12)]
    ts = [threading.Thread(target=pi.add, args=([u],)) for u in urls]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(pi.pending()) == 12


def test_no_active_profile_is_clear_error(env):
    with pytest.raises(RuntimeError, match="No active profile"):
        pi.add(["https://b.com/jobs/333333"])
