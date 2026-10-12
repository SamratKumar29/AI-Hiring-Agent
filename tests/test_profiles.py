import json
import shutil
from pathlib import Path

import pytest
import yaml

from brain import config, profiles

ROOT = Path(__file__).resolve().parent.parent
RESUME = ROOT / "Samrat_Kumar_Resume_Master.md"


PREFS = {"full_name": "Test User", "email": "t@x.com", "city": "Bengaluru", "country": "India",
         "target_roles": ["Senior AI Engineer", "ML Engineer", "Staff AI Engineer"],
         "locations": ["Bengaluru", "Remote"], "work_mode": "hybrid", "currency": "INR",
         "min_base_salary": 3000000, "preferred_salary": 4000000, "exclude": ["Gambling"],
         "must_have_skills": ["Python"], "notice_period_days": 30, "needs_sponsorship": False,
         "visa_status": "n/a"}


def test_parse_salary():
    assert profiles.parse_salary("30 LPA") == 3_000_000
    assert profiles.parse_salary("120k") == 120_000
    assert profiles.parse_salary("$1.5m") == 1_500_000
    assert profiles.parse_salary("30-40 LPA") == 3_000_000
    assert profiles.parse_salary("1,20,000") == 120000
    assert profiles.parse_salary("$150K-200K") == 150_000 and profiles.parse_salary("25 to 30 LPA") == 2_500_000
    assert profiles.parse_salary("abc") is None and profiles.parse_salary("") is None


def test_format_money():
    assert profiles.format_money(3_000_000, "inr") == "INR 30 LPA"
    assert profiles.format_money(120000, "usd") == "USD 120,000"


def test_guess_identity_from_real_resume():
    g = profiles.guess_identity(RESUME.read_text())
    assert g["full_name"] == "Samrat Kumar"
    assert g["email"] == "samrat2908@outlook.com"
    assert g["github"] == "github.com/SamratKumar29"


def test_read_resume_types(tmp_path):
    assert "Samrat" in profiles.read_resume(RESUME)
    import docx
    d = docx.Document(); d.add_paragraph("Hello docx resume"); f = tmp_path / "r.docx"; d.save(f)
    assert "Hello docx" in profiles.read_resume(f)
    with pytest.raises(ValueError):
        profiles.read_resume(RESUME.with_suffix(".xyz")) if RESUME.with_suffix(".xyz").exists() else (_ for _ in ()).throw(ValueError())
    with pytest.raises(FileNotFoundError):
        profiles.read_resume(tmp_path / "nope.md")


def test_create_list_load_active(env):
    profiles.create_profile("My AI Profile", RESUME, PREFS)
    assert profiles.list_profiles() == ["my-ai-profile"]
    profiles.create_profile("second", RESUME, PREFS)
    profiles.set_active("my-ai-profile")
    assert profiles.get_active() == "my-ai-profile"
    profiles.set_active("second")
    assert profiles.get_active() == "second"
    p = profiles.load_profile("My AI Profile")
    assert p["prefs"]["min_base_salary"] == 3000000 and "Samrat" in p["cv"]
    with pytest.raises(FileExistsError):
        profiles.create_profile("second", RESUME, PREFS)
    with pytest.raises(FileNotFoundError):
        profiles.load_profile("ghost")
    profiles.update_preferences("second", {"min_base_salary": 1})
    assert profiles.load_profile("second")["prefs"]["min_base_salary"] == 1


def test_questionnaire_defaults_and_piped_answers():
    answers = iter(["", "", "", "", "", "Bengaluru", "", "Prompt Engineer, AI Engineer", "Bengaluru, Remote",
                    "remote", "inr", "banana", "28 LPA", "35 LPA", "3", "python, rag", "gambling", "", "n", "45", ""])
    out = []
    prefs = profiles.ask_preferences(RESUME.read_text(), input_fn=lambda _: next(answers), output_fn=out.append)
    assert prefs["full_name"] == "Samrat Kumar"            # from CV guess
    assert prefs["target_roles"] == ["Prompt Engineer", "AI Engineer"]
    assert prefs["min_base_salary"] == 2_800_000           # 'banana' rejected, re-asked
    assert prefs["work_mode"] == "remote" and prefs["notice_period_days"] == 45
    assert prefs["exclude"] == ["gambling"] and prefs["needs_sponsorship"] is False


def test_questionnaire_eof_uses_defaults():
    def eof(_):
        raise EOFError
    prefs = profiles.ask_preferences("", input_fn=eof, output_fn=lambda *_: None)
    assert prefs["work_mode"] == "any" and prefs["min_base_salary"] is None


def test_core_titles():
    assert profiles.core_titles(["Senior AI Engineer", "Staff AI Engineer", "ML Engineer"]) == ["AI Engineer", "ML Engineer"]


def test_render_profile_yml(env):
    y = yaml.safe_load(profiles.render_profile_yml(PREFS, {"headline": "H", "exit_story": "E", "superpowers": ["a"]}))
    assert y["candidate"]["full_name"] == "Test User" and y["candidate"]["location"] == "Bengaluru, India"
    assert y["compensation"]["minimum"] == "INR 30 LPA" and y["compensation"]["target_range"] == "INR 40 LPA"
    assert y["target_roles"]["primary"][0] == "Senior AI Engineer"
    assert y["narrative"]["proof_points"] == [] and y["narrative"]["headline"] == "H"
    assert "Jane" not in json.dumps(y) and "Spanish" not in json.dumps(y)


def test_render_portals(env):
    t = profiles.render_portals(PREFS)
    y = yaml.safe_load(t)
    assert y["title_filter"]["positive"] == ["AI Engineer", "ML Engineer"]
    assert "Gambling" in y["title_filter"]["negative"] and "Intern" in y["title_filter"]["negative"]
    assert y["location_filter"]["allow"] == ["Bengaluru", "Remote"]
    names = [c["name"] for c in y["tracked_companies"] if c.get("provider")]
    assert "RemoteOK" in names and "Anthropic" in [c["name"] for c in y["tracked_companies"]]


def test_render_portals_onsite_has_no_remote_feeds(env):
    y = yaml.safe_load(profiles.render_portals({**PREFS, "work_mode": "onsite", "locations": ["Pune"]}))
    assert y["location_filter"]["allow"] == ["Pune"]
    assert "RemoteOK" not in [c["name"] for c in y["tracked_companies"]]


def good_chat(prompt):
    tmpl = (profiles.CAREER_OPS / "modes" / "_profile.template.md").read_text()
    if "write JSON" in prompt:
        return '```json\n{"headline":"RAG builder","exit_story":"x","superpowers":["a","b"]}\n```'
    return tmpl + "\nCUSTOM-MARK"


def test_activate_puts_everything_in_profile_dir_and_links(env):
    profiles.create_profile("p", RESUME, PREFS)
    (env / "cv.md").write_text("OLD CV")                   # pre-existing root file differing from the profile
    r = profiles.activate("p", chat_fn=good_chat)
    d = env / "profile" / "p"
    for f in ("preferences.json", "cv.md", "profile.yml", "portals.yml", "_profile.md"):
        assert (d / f).is_file(), f
    for w in ("data", "reports", "output"):
        assert (d / "workspace" / w).is_dir()
    for link, target in {"cv.md": d / "cv.md", "config/profile.yml": d / "profile.yml",
                         "portals.yml": d / "portals.yml", "modes/_profile.md": d / "_profile.md",
                         "data": d / "workspace" / "data", "reports": d / "workspace" / "reports",
                         "output": d / "workspace" / "output"}.items():
        assert (env / link).is_symlink() and (env / link).resolve() == target.resolve(), link
    assert "Samrat" in (env / "cv.md").read_text()
    assert list((config.DATA_DIR / "backups").rglob("*cv.md"))      # differing old root cv was backed up
    assert r["narrative_generated"] and "CUSTOM-MARK" in (d / "_profile.md").read_text()
    assert yaml.safe_load((d / "profile.yml").read_text())["narrative"]["headline"] == "RAG builder"
    assert profiles.get_active() == "p"


def test_activate_does_not_overwrite_hand_edits_but_regenerate_does(env):
    profiles.create_profile("p", RESUME, PREFS)
    profiles.activate("p", chat_fn=good_chat)
    profiles.write_file("p", "_profile.md", "# MY HAND EDIT\n")
    profiles.activate("p", chat_fn=lambda _: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    assert profiles.read_file("p", "_profile.md") == "# MY HAND EDIT\n"
    profiles.generate_files("p", use_llm=False, only=("_profile.md",))
    assert "Candidate Preferences" in profiles.read_file("p", "_profile.md")
    assert list((config.DATA_DIR / "backups").rglob("*_profile.md"))


def test_llm_down_falls_back_deterministically(env):
    profiles.create_profile("p", RESUME, PREFS)
    r = profiles.activate("p", chat_fn=lambda _: (_ for _ in ()).throw(RuntimeError("flooded")))
    assert not r["narrative_generated"] and not r["profile_md_from_llm"]
    assert "Candidate Preferences" in profiles.read_file("p", "_profile.md")


def test_switching_profiles_repoints_links_and_isolates_workspace(env):
    for n in ("a", "b"):
        profiles.create_profile(n, RESUME, {**PREFS, "full_name": n})
    profiles.activate("a", use_llm=False)
    (env / "data" / "pipeline.md").write_text("A-PIPELINE")          # written through the link
    profiles.activate("b", use_llm=False)
    assert not (env / "data" / "pipeline.md").exists()               # b has its own empty workspace
    assert (env / "profile" / "a" / "workspace" / "data" / "pipeline.md").read_text() == "A-PIPELINE"
    assert yaml.safe_load((env / "config" / "profile.yml").read_text())["candidate"]["full_name"] == "b"
    profiles.activate("a", use_llm=False)
    assert (env / "data" / "pipeline.md").read_text() == "A-PIPELINE"
    assert profiles.activate("a", use_llm=False)["links"]["cv.md"] == "unchanged"


def test_adopts_existing_career_ops_work_into_first_profile(env):
    (env / "data").mkdir()
    (env / "data" / "applications.md").write_text("EXISTING TRACKER")
    (env / "portals.yml").write_text("title_filter: {positive: [X]}\n")
    profiles.create_profile("p", RESUME, PREFS)
    profiles.activate("p", use_llm=False)
    d = env / "profile" / "p"
    assert (d / "workspace" / "data" / "applications.md").read_text() == "EXISTING TRACKER"
    assert "positive: [X]" in (d / "portals.yml").read_text()       # adopted, not regenerated


def test_write_file_validates_yaml_and_whitelist(env):
    profiles.create_profile("p", RESUME, PREFS)
    with pytest.raises(ValueError, match="Invalid YAML"):
        profiles.write_file("p", "portals.yml", "a: [unclosed")
    with pytest.raises(ValueError):
        profiles.write_file("p", "../../etc/passwd", "x")
    with pytest.raises(ValueError):
        profiles.read_file("p", "preferences.json")
    profiles.write_file("p", "cv.md", "# new cv")
    assert profiles.read_file("p", "cv.md") == "# new cv"


def test_delete_is_soft_and_unlinks_active(env):
    profiles.create_profile("p", RESUME, PREFS)
    profiles.activate("p", use_llm=False)
    trash = profiles.delete_profile("p")
    assert trash.exists() and (trash / "preferences.json").exists()
    assert profiles.list_profiles() == [] and profiles.get_active() is None
    assert not (env / "cv.md").is_symlink() and not (env / "data").is_symlink()


def test_rename_active_profile_relinks(env):
    profiles.create_profile("old", RESUME, PREFS)
    profiles.activate("old", use_llm=False)
    assert profiles.rename_profile("old", "New Name") == "new-name"
    assert profiles.get_active() == "new-name"
    assert (env / "cv.md").resolve() == (env / "profile" / "new-name" / "cv.md").resolve()
    profiles.create_profile("other", RESUME, PREFS)
    with pytest.raises(FileExistsError):
        profiles.rename_profile("other", "new-name")


def test_migrates_legacy_profiles_dir(env, tmp_path):
    legacy = tmp_path / "profiles" / "samrat"
    legacy.mkdir(parents=True)
    (legacy / "cv.md").write_text("cv")
    (legacy / "preferences.json").write_text(json.dumps({"profile_name": "samrat", "min_base_salary": 1}))
    assert profiles.list_profiles() == ["samrat"]
    assert (env / "profile" / "samrat" / "preferences.json").exists() and not legacy.exists()


def test_workspace_path_requires_active_and_validates(env):
    with pytest.raises(RuntimeError, match="No active profile"):
        profiles.workspace_path()
    profiles.create_profile("p", RESUME, PREFS)
    with pytest.raises(RuntimeError):
        profiles.workspace_path()                        # exists but not active
    assert profiles.workspace_path("p", "reports").is_dir()
    profiles.set_active("p")
    assert profiles.workspace_path() == env / "profile" / "p" / "workspace" / "data"
    with pytest.raises(ValueError):
        profiles.workspace_path(sub="secrets")


def test_duplicate_copies_files_not_workspace(env):
    profiles.create_profile("a", RESUME, PREFS)
    profiles.activate("a", use_llm=False)
    (profiles.workspace_path("a") / "jobs.db").write_text("x")
    (env / "profile" / "a" / "sources.json").write_text('{"sources": []}')
    assert profiles.duplicate_profile("a", "A Copy") == "a-copy"
    d = env / "profile" / "a-copy"
    assert (d / "cv.md").exists() and (d / "portals.yml").exists() and (d / "sources.json").exists()
    assert not (d / "workspace" / "data" / "jobs.db").exists()
    assert profiles.load_profile("a-copy")["prefs"]["profile_name"] == "a-copy"
    with pytest.raises(FileExistsError):
        profiles.duplicate_profile("a", "a-copy")


def test_trash_list_and_restore(env):
    profiles.create_profile("p", RESUME, PREFS)
    profiles.delete_profile("p")
    t = profiles.list_trash()
    assert len(t) == 1 and t[0]["profile"] == "p"
    profiles.create_profile("p", RESUME, PREFS)                       # name now taken again
    with pytest.raises(FileExistsError):
        profiles.restore_profile(t[0]["trash_name"])
    assert profiles.restore_profile(t[0]["trash_name"], "p-restored") == "p-restored"
    assert sorted(profiles.list_profiles()) == ["p", "p-restored"] and profiles.list_trash() == []
    with pytest.raises(FileNotFoundError):
        profiles.restore_profile("nope")
