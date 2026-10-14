import pytest

from brain import config, llm


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.text = status, body or {}, str(body)

    def json(self):
        return self._b


OK = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2,m3")
    monkeypatch.setenv("OPENROUTER_PAID_FALLBACK", "")


def test_models_parse():
    assert config.models() == ["m1", "m2", "m3"]


def test_fallback_to_second_model(monkeypatch):
    calls = []

    def fake_post(url, json, **kw):
        calls.append(json["model"])
        return Resp(429, {}) if json["model"] == "m1" else Resp(200, OK)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    text, used = llm.chat([{"role": "user", "content": "x"}], backoff=0)
    assert (text, used) == ("OK", "m2")
    assert calls.count("m1") == llm.RETRIES_PER_MODEL + 1


def test_empty_response_counts_as_failure(monkeypatch):
    def fake_post(url, json, **kw):
        return Resp(200, {"choices": [{"message": {"content": ""}}]}) if json["model"] == "m1" else Resp(200, OK)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "x"}], backoff=0)[1] == "m2"


def test_all_fail_raises_without_leaking_key(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp(500, {"e": "sk-test boom"}))
    with pytest.raises(llm.LLMUnavailable) as ei:
        llm.chat([{"role": "user", "content": "x"}], backoff=0)
    assert "sk-test" not in str(ei.value)
    assert set(ei.value.errors) == {"m1", "m2", "m3"}


def test_bad_key_fails_fast(monkeypatch):
    n = []
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: (n.append(1), Resp(401, {}))[1])
    with pytest.raises(llm.LLMUnavailable):
        llm.chat([{"role": "user", "content": "x"}], backoff=0)
    assert len(n) == 1


def test_missing_key_message(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    with pytest.raises(RuntimeError, match=".env"):
        config.api_key()


def test_paid_fallback_accepts_list(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PAID_FALLBACK", "p1, p2")
    assert config.models() == ["m1", "m2", "m3", "p1", "p2"]


def test_404_skips_model_without_retry(monkeypatch):
    calls = []

    def fake_post(url, json, **kw):
        calls.append(json["model"])
        return Resp(404, {}) if json["model"] == "m1" else Resp(200, OK)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "x"}], backoff=0)[1] == "m2"
    assert calls.count("m1") == 1


def test_healthy_model_skips_flooded(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, json, **kw: Resp(429, {}) if json["model"] == "m1" else Resp(200, OK))
    assert llm.healthy_model() == "m2"
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: 1 / 0)  # cached: no network
    assert llm.healthy_model() == "m2"


def test_validate_rejects_unusable_answer_and_moves_on_without_retrying(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODELS", "a,b")
    monkeypatch.delenv("OPENROUTER_PAID_FALLBACK", raising=False)
    calls = []

    def fake(model, messages, max_tokens, timeout, key):
        calls.append(model)
        return "<tool_call>x</tool_call>" if model == "a" else "A real answer"
    monkeypatch.setattr(llm, "_call", fake)
    text, used = llm.chat([{"role": "user", "content": "hi"}], validate=lambda t: "tool call" if "<tool_call>" in t else None)
    assert (text, used) == ("A real answer", "b") and calls == ["a", "b"]           # 'a' tried once only
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.chat([{"role": "user", "content": "hi"}], validate=lambda t: "never good")
    assert "unusable: never good" in str(e.value)
