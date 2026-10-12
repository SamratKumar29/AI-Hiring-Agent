from brain import filter as flt, jobs_db, profiles


def J(i, **kw):
    return {"url": f"https://x.com/jobs/{100000 + i}", "title": f"Role {i}", "company": f"Co{i}", "source": "t", **kw}


def prefs(**kw):
    return {"min_base_salary": 2_000_000, "currency": "INR", "exclude": ["Gambling", "Gurgaon"],
            "locations": ["Bengaluru", "Remote"], "work_mode": "hybrid", "country": "India", **kw}


def test_salary_rules():
    p = prefs()
    assert flt.evaluate({"salary_text": "₹10L – ₹15L"}, p).startswith("below_salary")
    assert flt.evaluate({"salary_text": "₹15L – ₹30L"}, p) is None            # range reaches the minimum
    assert flt.evaluate({"salary_text": "$100k"}, p) is None                  # ~83L INR
    assert flt.evaluate({"salary_text": "$10k"}, p).startswith("below_salary")  # ~8.3L INR
    assert flt.evaluate({"salary_text": ""}, p) is None and flt.evaluate({"salary_text": "Competitive"}, p) is None
    assert flt.evaluate({"salary_text": "₹20,000 – ₹30,000"}, p).startswith("below_salary")   # monthly intern pay
    assert flt.evaluate({"salary_text": "₹10L"}, prefs(min_base_salary=None)) is None


def test_exclude_terms_whole_word_in_company_title_location():
    p = prefs()
    assert flt.evaluate({"company": "BetKing Gambling Ltd"}, p) == "excluded: Gambling"
    assert flt.evaluate({"title": "AI Engineer", "location": "Gurgaon, India"}, p) == "excluded: Gurgaon"
    assert flt.evaluate({"company": "Gamblingly"}, p) is None                   # not a whole word
    assert flt.evaluate({"title": "AI Eng", "description": "x" * 500 + " gambling"}, p) is None   # only the start counts


def test_location_and_mode_rules():
    p = prefs()
    assert flt.evaluate({"location": "Bangalore, Karnataka"}, p) is None        # alias of Bengaluru
    assert flt.evaluate({"location": "Remote - Worldwide"}, p) is None
    assert flt.evaluate({"location": ""}, p) is None                            # unknown kept
    assert flt.evaluate({"location": "London, UK"}, p).startswith("location")
    assert flt.evaluate({"location": "Pune, India"}, p) is None                 # same country is fine
    assert flt.evaluate({"location": "Remote"}, prefs(work_mode="onsite", locations=["Bengaluru"])).startswith("location")
    r = prefs(work_mode="remote")
    assert flt.evaluate({"location": "Bengaluru", "description": "office based"}, r).startswith("location")
    assert flt.evaluate({"location": "Bengaluru", "description": "fully remote team"}, r) is None
    assert flt.evaluate({"location": "Paris"}, prefs(locations=["Any"])) is None


def test_apply_marks_dismissed_with_reason_and_dedupes(active):
    profiles.update_preferences("p", {"min_base_salary": 2_000_000, "currency": "INR", "exclude": ["Gambling"],
                                      "locations": ["Bengaluru"], "work_mode": "hybrid"})
    jobs_db.upsert_jobs([
        J(1, salary_text="₹10L – ₹12L"),                                           # low salary
        J(2, company="Gambling Co"),                                               # excluded
        J(3, location="Tokyo"),                                                    # wrong place
        J(4, company="Acme", title="AI Eng", location="Bengaluru", found_at="2026-01-01 10:00:00"),
        J(5, company="ACME", title="ai  eng", location="Bengaluru", found_at="2026-01-02 10:00:00"),   # duplicate
        J(6, salary_text="", location=""),                                          # unknown everything: keep
        J(7, salary_text="₹30L", location="Bengaluru"),                             # good
    ], name="p")
    dry = flt.apply("p", dry_run=True)
    assert len(dry["dropped"]) == 4 and jobs_db.count(decision="dismissed", name="p") == 0
    r = flt.apply("p")
    assert r["by_reason"] == {"below_salary": 1, "excluded": 1, "location": 1, "duplicate": 1} and len(r["kept"]) == 3
    d = jobs_db.get_job(jobs_db.job_id("https://x.com/jobs/100001"), "p")
    assert d["decision"] == "dismissed" and d["notes"].startswith("auto-filter: below_salary")
    assert jobs_db.count(decision="new", name="p") == 3
    assert flt.apply("p")["dropped"] == []                                         # idempotent


def test_user_decisions_are_not_overridden_and_synced_jobs_block_duplicates(active):
    profiles.update_preferences("p", {"min_base_salary": 5_000_000, "currency": "INR", "locations": ["Any"]})
    jobs_db.upsert_jobs([J(1, salary_text="₹10L"), J(2, company="Acme", title="AI Eng"),
                         J(3, company="Acme", title="AI Eng")], name="p")
    jobs_db.set_decision(jobs_db.job_id("https://x.com/jobs/100001"), "liked", name="p")      # user liked a low-pay job
    jobs_db.mark_synced([jobs_db.job_id("https://x.com/jobs/100002")], "p")                   # already in pipeline
    r = flt.apply("p")
    assert jobs_db.get_job(jobs_db.job_id("https://x.com/jobs/100001"), "p")["decision"] == "liked"
    assert [d["reason"].split(":")[0] for d in r["dropped"]] == ["duplicate"]
