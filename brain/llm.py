"""OpenRouter chat client with model fallback and retries."""
import time

import requests

from brain import config

HEADERS_EXTRA = {
    "HTTP-Referer": "https://github.com/SamratKumar29/AI-Hiring-Agent",
    "X-Title": "AI-Hiring-Agent",
}
RETRIES_PER_MODEL = 2


class LLMUnavailable(RuntimeError):
    """Raised when every model failed. .errors maps model -> last error."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("All models failed: " + "; ".join(f"{m}: {e}" for m, e in errors.items()))


def _call(model: str, messages: list, max_tokens: int, timeout: int, key: str) -> str:
    r = requests.post(
        f"{config.OPENROUTER_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}", **HEADERS_EXTRA},
        json={"model": model, "messages": messages, "max_tokens": max_tokens},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"API error: {str(data['error'])[:160]}")
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not text.strip():
        raise RuntimeError("empty response")
    return text


def chat(messages: list, model: str | None = None, max_tokens: int = 512,
         timeout: int = 60, backoff: float = 1.0) -> tuple[str, str]:
    """Return (text, model_used). Tries `model` first (if given), then the configured list."""
    key = config.api_key()
    order = ([model] if model else []) + [m for m in config.models() if m != model]
    if not order:
        raise RuntimeError("No models configured (OPENROUTER_MODELS is empty).")
    errors: dict = {}
    for m in order:
        for attempt in range(RETRIES_PER_MODEL + 1):
            try:
                return _call(m, messages, max_tokens, timeout, key), m
            except Exception as e:  # noqa: BLE001
                errors[m] = str(e).replace(key, "***")
                if "HTTP 401" in errors[m] or "HTTP 403" in errors[m]:
                    raise LLMUnavailable(errors) from None
                if "HTTP 404" in errors[m] or "HTTP 400" in errors[m]:
                    break  # model unusable via chat/completions; try the next one
                if attempt < RETRIES_PER_MODEL:
                    time.sleep(backoff * (2 ** attempt))
    raise LLMUnavailable(errors)


def probe(model: str, timeout: int = 45) -> dict:
    """ONE quick attempt (no retries). Returns {model, ok, latency_s, error}."""
    t0 = time.time()
    if model.endswith(":batch"):
        return {"model": model, "ok": False, "latency_s": 0, "error": "skipped: :batch variants don't support chat"}
    key = config.api_key()
    try:
        _call(model, [{"role": "user", "content": "Reply with exactly: OK"}], 512, timeout, key)
        return {"model": model, "ok": True, "latency_s": round(time.time() - t0, 2), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"model": model, "ok": False, "latency_s": round(time.time() - t0, 2),
                "error": str(e).replace(key, "***")[:140]}


def select_model(cache_minutes: int = 10, force: bool = False, on_result=None) -> dict:
    """Probe free models in order (1 try each); first that answers wins.
    If ALL free models fail, probe the paid tier the same way.
    Returns {model, tier ('free'|'paid'), results:[...]}; raises LLMUnavailable if none work."""
    import json

    cache = config.DATA_DIR / "selected_model.json"
    tiers = {"free": config.free_models(), "paid": config.paid_models()}
    if not force:
        try:
            c = json.loads(cache.read_text())
            if c.get("tiers") == tiers and time.time() - c["ts"] < cache_minutes * 60:
                return c["selection"]
        except Exception:  # noqa: BLE001
            pass
    results: list = []
    for tier, names in tiers.items():
        for m in names:
            r = {**probe(m), "tier": tier}
            results.append(r)
            if on_result:
                on_result(r)
            if r["ok"]:
                sel = {"model": m, "tier": tier, "results": results}
                config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"tiers": tiers, "ts": time.time(), "selection": sel}))
                return sel
    raise LLMUnavailable({r["model"]: r["error"] for r in results})


def healthy_model(cache_minutes: int = 10) -> str:
    """Model to hand to tools that accept only ONE model."""
    return select_model(cache_minutes)["model"]
