import subprocess

import pytest

from brain import config, llm, sync_env


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2:batch,m3")
    monkeypatch.setenv("OPENROUTER_PAID_FALLBACK", "")


def test_export_env_names():
    e = sync_env.export_env(probe=False)
    assert e["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert e["OPENAI_API_KEY"] == e["LLM_API_KEY"] == e["OPENROUTER_API_KEY"] == "sk-test"
    assert e["LLM_MODEL"] == "openrouter/m1"


def _fake_run(results):
    calls = []

    def run(cmd, cwd, env, **kw):
        calls.append(env["CAREER_OPS_MODEL"])
        out, rc = results[env["CAREER_OPS_MODEL"]]
        return subprocess.CompletedProcess(cmd, rc, out, "")

    return run, calls


def test_fallback_skips_batch_and_failed(monkeypatch):
    run, calls = _fake_run({"m1": ("OpenRouter error: HTTP 429", 0), "m3": ("all good", 0)})
    monkeypatch.setattr(sync_env.subprocess, "run", run)
    r, used = sync_env.run_with_fallback(["x"], ".")
    assert used == "m3" and calls == ["m1", "m3"]


def test_fallback_all_fail(monkeypatch):
    run, _ = _fake_run({"m1": ("Empty response", 0), "m3": ("", 1)})
    monkeypatch.setattr(sync_env.subprocess, "run", run)
    with pytest.raises(llm.LLMUnavailable) as ei:
        sync_env.run_with_fallback(["x"], ".")
    assert set(ei.value.errors) == {"m1", "m3"}


def test_run_with_fallback_validate_rejects_empty_success(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from brain import config, sync_env
    monkeypatch.setattr(sync_env, "export_env", lambda probe=True: {"OPENROUTER_API_KEY": "k"})
    seen = []

    def fake_run(cmd, cwd, env, capture_output, text, timeout):
        seen.append(env["CAREER_OPS_MODEL"])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    r, m = sync_env.run_with_fallback(["x"], ".", models=["a", "b", "c"], validate=lambda p, model: "empty" if model != "c" else None)
    assert m == "c" and seen == ["a", "b", "c"]
    import pytest
    with pytest.raises(Exception) as e:
        sync_env.run_with_fallback(["x"], ".", models=["a"], validate=lambda p, model: "no score")
    assert "no score" in str(e.value)
