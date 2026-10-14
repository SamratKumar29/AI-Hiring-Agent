import shutil
from pathlib import Path

import pytest

from brain import config, profiles

ROOT = Path(__file__).resolve().parent.parent
RESUME = ROOT / "tests" / "fixtures" / "sample_cv.md"       # fictional person; never use a real CV in tests
PREFS = {"full_name": "Test User", "email": "t@x.com", "city": "Bengaluru", "country": "India",
         "target_roles": ["Senior AI Engineer", "ML Engineer", "Staff AI Engineer"],
         "locations": ["Bengaluru", "Remote"], "work_mode": "hybrid", "currency": "INR",
         "min_base_salary": 3000000, "preferred_salary": 4000000, "exclude": ["Gambling"],
         "must_have_skills": ["Python"], "notice_period_days": 30, "needs_sponsorship": False,
         "visa_status": "n/a"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    co = tmp_path / "career-ops"
    (co / "config").mkdir(parents=True)
    (co / "templates").mkdir()
    (co / "modes").mkdir()
    src = ROOT / "career-ops"
    shutil.copy(src / "config" / "profile.example.yml", co / "config")
    shutil.copy(src / "templates" / "portals.example.yml", co / "templates")
    shutil.copy(src / "modes" / "_profile.template.md", co / "modes")
    monkeypatch.setattr(profiles, "PROFILES_DIR", co / "profile")
    monkeypatch.setattr(profiles, "LEGACY_PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profiles, "CAREER_OPS", co)
    monkeypatch.setattr(profiles, "_hide_tracked_placeholders", lambda: None)
    monkeypatch.setattr(profiles, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return co



@pytest.fixture
def active(env):
    """An activated profile 'p' (files generated without the LLM)."""
    profiles.create_profile("p", RESUME, PREFS)
    profiles.activate("p", use_llm=False)
    return "p"


@pytest.fixture(autouse=True)
def _no_spend_lookup(monkeypatch, request):
    """Tests never call OpenRouter's /auth/key; test_budget.py replaces this stub itself."""
    if request.module.__name__.endswith("test_budget"):
        return
    from brain import budget
    monkeypatch.setattr(budget, "usage", lambda: {"ok": True, "monthly": 0.0, "limit_remaining": None, "error": None})
