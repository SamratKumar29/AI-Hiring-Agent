import pytest

from brain import config, llm


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.text = status, body or {}, str(body)

    def json(self):
        return self._b


OK = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODELS", "f1,f2:batch,f3")
    monkeypatch.setenv("OPENROUTER_PAID_FALLBACK", "p1,p2,f1")


def fake(working, calls):
    def post(url, json, **kw):
        calls.append(json["model"])
        return Resp(200, OK) if json["model"] in working else Resp(429, {})
    return post


def test_tiers_split():
    assert config.free_models() == ["f1", "f2:batch", "f3"]
    assert config.paid_models() == ["p1", "p2"]  # f1 duplicate removed


def test_first_free_model_wins_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.requests, "post", fake({"f1", "f3", "p1"}, calls))
    sel = llm.select_model(force=True)
    assert (sel["model"], sel["tier"]) == ("f1", "free")
    assert calls == ["f1"]


def test_one_attempt_per_model_and_batch_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.requests, "post", fake({"f3"}, calls))
    sel = llm.select_model(force=True)
    assert sel["model"] == "f3"
    assert calls == ["f1", "f3"]  # f1 tried once, :batch never called
    assert [r["ok"] for r in sel["results"]] == [False, False, True]


def test_paid_tier_only_when_all_free_fail(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.requests, "post", fake({"p2"}, calls))
    sel = llm.select_model(force=True)
    assert (sel["model"], sel["tier"]) == ("p2", "paid")
    assert calls == ["f1", "f3", "p1", "p2"]


def test_all_fail_raises(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", fake(set(), []))
    with pytest.raises(llm.LLMUnavailable):
        llm.select_model(force=True)


def test_cache_used_then_invalidated_when_config_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.requests, "post", fake({"f1"}, calls))
    llm.select_model(force=True)
    n = len(calls)
    assert llm.select_model()["model"] == "f1" and len(calls) == n
    monkeypatch.setenv("OPENROUTER_MODELS", "f3,f1")
    llm.select_model()
    assert len(calls) > n
