"""Send messages to the user: Telegram now, email when SMTP_* is filled in. Never raises.

    send(subject, body) -> {"telegram": {"ok": bool, "detail": str}, "email": {...}}
A channel whose settings are empty reports {"ok": False, "skipped": True}.
"""
import smtplib
import ssl
from email.message import EmailMessage

import requests

from brain import config

API = "https://api.telegram.org/bot{token}/{method}"
CHUNK = 4000                       # Telegram's hard limit is 4096 characters per message


def _clean(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def chunks(text: str, size: int = CHUNK) -> list[str]:
    """Split on blank lines / line ends so a job entry is never cut in half where possible."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        para = para.rstrip()
        while len(para) > size:                                  # one giant paragraph: cut at a line end
            cut = para.rfind("\n", 0, size)
            cut = cut if cut > 0 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut])
            para = para[cut:].lstrip("\n")
        if len(cur) + len(para) + 2 > size and cur:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        out.append(cur)
    return out or [""]


def telegram_call(method: str, token: str, timeout: int = 20, **payload) -> dict:
    r = requests.post(API.format(token=token, method=method), json=payload, timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        data = {"ok": False, "description": f"HTTP {r.status_code}"}
    return data


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None) -> dict:
    token = token or config.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or config.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"ok": False, "skipped": True, "detail": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (run: hire.py notify setup)"}
    sent = 0
    try:
        for part in chunks(text):
            d = telegram_call("sendMessage", token, chat_id=chat_id, text=part, disable_web_page_preview=True)
            if not d.get("ok"):
                return {"ok": False, "detail": _clean(f"Telegram refused after {sent} part(s): {d.get('description', d)}", [token])}
            sent += 1
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _clean(f"{type(e).__name__}: {e}", [token])}
    return {"ok": True, "detail": f"{sent} message(s) sent"}


def send_email(subject: str, body: str) -> dict:
    host, user, pw = config.get("SMTP_HOST"), config.get("SMTP_USER"), config.get("SMTP_PASSWORD")
    if not (host and user and pw):
        return {"ok": False, "skipped": True, "detail": "SMTP_USER / SMTP_PASSWORD not set"}
    to = config.get("EMAIL_TO") or user
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, user, to
        msg.set_content(body)
        with smtplib.SMTP(host, int(config.get("SMTP_PORT", "587") or 587), timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
            s.send_message(msg)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _clean(f"{type(e).__name__}: {e}", [pw, user])}
    return {"ok": True, "detail": f"sent to {to}"}


def send(subject: str, body: str) -> dict:
    """Deliver on every configured channel. Telegram gets 'subject' as the first line."""
    return {"telegram": send_telegram(f"{subject}\n\n{body}" if subject else body),
            "email": send_email(subject, body)}


def delivered(result: dict) -> bool:
    return any(v.get("ok") for v in result.values())


# ---- setup helpers -------------------------------------------------------------------------------
def check_token(token: str) -> dict:
    """-> {"ok", "username", "detail"} using Telegram's getMe."""
    try:
        d = telegram_call("getMe", token, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "network": True, "detail": _clean(f"{type(e).__name__}: {e}", [token])}
    if d.get("ok"):
        return {"ok": True, "username": d["result"].get("username"), "detail": "token is valid"}
    return {"ok": False, "rejected": True, "detail": f"Telegram says: {d.get('description', 'invalid token')}"}


def find_chat_id(token: str) -> dict:
    """Find the chat that last wrote to the bot. -> {"ok", "chat_id", "name", "detail"}"""
    try:
        d = telegram_call("getUpdates", token, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _clean(f"{type(e).__name__}: {e}", [token])}
    if not d.get("ok"):
        return {"ok": False, "detail": f"Telegram says: {d.get('description')}"}
    for upd in reversed(d.get("result", [])):
        chat = (upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member") or {}).get("chat")
        if chat and chat.get("type") == "private":
            name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or "you"
            return {"ok": True, "chat_id": str(chat["id"]), "name": name, "detail": "found"}
    return {"ok": False, "detail": "No message found. Open your bot in Telegram, press Start, send it 'hi', then run this again."}
