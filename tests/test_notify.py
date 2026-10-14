import smtplib

import pytest
import requests

from brain import config, notify

TOKEN = "123456:SECRET-TOKEN-abc"


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        if self._d is None:
            raise ValueError("not json")
        return self._d


@pytest.fixture
def tg(monkeypatch):
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return calls_reply.pop(0) if calls_reply else Resp({"ok": True, "result": {}})
    calls_reply = []
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(config, "get", lambda k, d="": {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"}.get(k, d))
    return type("T", (), {"calls": calls, "reply": calls_reply})


def test_chunks_respect_limit_and_keep_all_text():
    para = "line one of a job\nline two\n   https://x.com/jobs/1"
    text = "\n\n".join(f"{i}. {para}" for i in range(300))
    parts = notify.chunks(text, 1000)
    assert len(parts) > 3 and all(len(p) <= 1000 for p in parts)
    assert "".join(parts).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_chunks_splits_a_single_giant_paragraph_and_handles_empty():
    big = "\n".join(f"row {i} " + "x" * 50 for i in range(200))
    parts = notify.chunks(big, 500)
    assert all(len(p) <= 500 for p in parts) and len(parts) > 5
    assert notify.chunks("") == [""] and notify.chunks("short") == ["short"]
    assert all(len(p) <= 100 for p in notify.chunks("y" * 450, 100))                # no line breaks at all


def test_send_telegram_posts_with_expected_payload(tg):
    r = notify.send_telegram("hello")
    assert r == {"ok": True, "detail": "1 message(s) sent"}
    url, payload = tg.calls[0]
    assert url.endswith(f"/bot{TOKEN}/sendMessage")
    assert payload == {"chat_id": "42", "text": "hello", "disable_web_page_preview": True}


def test_long_message_is_sent_in_parts(tg):
    r = notify.send_telegram("\n\n".join("z" * 900 for _ in range(10)))
    assert r["ok"] and len(tg.calls) >= 3 and all(len(c[1]["text"]) <= 4000 for c in tg.calls)


def test_telegram_refusal_is_reported_and_stops(tg):
    tg.reply[:] = [Resp({"ok": True}), Resp({"ok": False, "description": "Forbidden: bot was blocked by the user"})]
    r = notify.send_telegram("\n\n".join("z" * 3000 for _ in range(5)))
    assert not r["ok"] and "blocked by the user" in r["detail"] and "after 1 part" in r["detail"] and len(tg.calls) == 2


def test_network_error_never_raises_and_never_leaks_token(tg, monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError(f"failed for https://api.telegram.org/bot{TOKEN}/sendMessage")
    monkeypatch.setattr(requests, "post", boom)
    r = notify.send_telegram("x")
    assert not r["ok"] and TOKEN not in r["detail"] and "***" in r["detail"]
    assert notify.check_token(TOKEN)["network"] is True and TOKEN not in notify.check_token(TOKEN)["detail"]


def test_non_json_reply_is_handled(tg):
    tg.reply[:] = [Resp(None, 502)]
    r = notify.send_telegram("x")
    assert not r["ok"] and "502" in r["detail"]


def test_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "get", lambda k, d="": d)
    assert notify.send_telegram("x")["skipped"] and notify.send_email("s", "b")["skipped"]
    res = notify.send("s", "b")
    assert not notify.delivered(res) and all(v["skipped"] for v in res.values())


def test_check_token_and_find_chat_id(tg):
    tg.reply[:] = [Resp({"ok": True, "result": {"username": "my_bot"}})]
    assert notify.check_token(TOKEN) == {"ok": True, "username": "my_bot", "detail": "token is valid"}
    tg.reply[:] = [Resp({"ok": False, "description": "Unauthorized"})]
    assert notify.check_token(TOKEN)["rejected"] is True
    updates = [{"message": {"chat": {"id": -100, "type": "group"}}},
               {"message": {"chat": {"id": 777, "type": "private", "first_name": "Sam", "last_name": "K"}}}]
    tg.reply[:] = [Resp({"ok": True, "result": updates})]
    f = notify.find_chat_id(TOKEN)
    assert f["ok"] and f["chat_id"] == "777" and f["name"] == "Sam K"
    tg.reply[:] = [Resp({"ok": True, "result": []})]
    assert not notify.find_chat_id(TOKEN)["ok"]


def test_email_sent_with_starttls_and_errors_hide_password(monkeypatch):
    env = {"SMTP_HOST": "smtp.x.com", "SMTP_PORT": "587", "SMTP_USER": "me@x.com", "SMTP_PASSWORD": "PW123", "EMAIL_TO": "you@x.com"}
    monkeypatch.setattr(config, "get", lambda k, d="": env.get(k, d))
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): log.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): log.append("starttls")
        def login(self, u, p): log.append(("login", u))
        def send_message(self, m): log.append(("to", m["To"], m["Subject"]))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert notify.send_email("Subj", "Body")["ok"]
    assert log == [("connect", "smtp.x.com", 587), "starttls", ("login", "me@x.com"), ("to", "you@x.com", "Subj")]

    class Bad(FakeSMTP):
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, f"bad login {p}".encode())
    monkeypatch.setattr(smtplib, "SMTP", Bad)
    r = notify.send_email("s", "b")
    assert not r["ok"] and "PW123" not in r["detail"]


def test_set_env_value_keeps_other_lines_and_mode(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nOPENROUTER_API_KEY=keep\nTELEGRAM_CHAT_ID=\nOTHER=1\n")
    monkeypatch.setattr(config, "ENV_FILE", f)
    config.set_env_value("TELEGRAM_CHAT_ID", "777")
    config.set_env_value("NEW_ONE", "x")
    assert f.read_text() == "# comment\nOPENROUTER_API_KEY=keep\nTELEGRAM_CHAT_ID=777\nOTHER=1\nNEW_ONE=x\n"
    assert oct(f.stat().st_mode)[-3:] == "600"
    with pytest.raises(ValueError):
        config.set_env_value("A", "x\ny")
