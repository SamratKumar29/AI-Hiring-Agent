"""Cost safety: cap evaluations per run and stop when this month's OpenRouter spend passes a limit."""
import requests

from brain import config

DEFAULT_MAX_EVALS = 20
DEFAULT_MONTHLY_LIMIT_USD = 5.0


class BudgetExceeded(RuntimeError):
    pass


def max_evals() -> int:
    try:
        n = int(config.get("MAX_EVALS_PER_RUN", str(DEFAULT_MAX_EVALS)) or DEFAULT_MAX_EVALS)
    except ValueError:
        n = DEFAULT_MAX_EVALS
    return max(1, n)


def monthly_limit() -> float:
    """MONTHLY_SPEND_LIMIT_USD; 0 disables the guard."""
    try:
        return max(0.0, float(config.get("MONTHLY_SPEND_LIMIT_USD", str(DEFAULT_MONTHLY_LIMIT_USD)) or 0))
    except ValueError:
        return DEFAULT_MONTHLY_LIMIT_USD


def usage() -> dict:
    """-> {"ok", "monthly", "limit_remaining", "error"} from OpenRouter /auth/key (never raises)."""
    try:
        r = requests.get(f"{config.OPENROUTER_BASE}/auth/key", headers={"Authorization": f"Bearer {config.api_key()}"}, timeout=20)
        if r.status_code != 200:
            return {"ok": False, "monthly": None, "limit_remaining": None, "error": f"HTTP {r.status_code}"}
        d = r.json().get("data", {})
        return {"ok": True, "monthly": float(d.get("usage_monthly") or 0), "limit_remaining": d.get("limit_remaining"), "error": None}
    except (requests.RequestException, RuntimeError, ValueError) as e:
        return {"ok": False, "monthly": None, "limit_remaining": None, "error": str(e)[:100]}


def check() -> dict:
    """-> {"allowed", "reason", "monthly", "limit"}. Fails OPEN when usage cannot be read (the LLM calls would fail anyway)."""
    limit, u = monthly_limit(), usage()
    out = {"allowed": True, "reason": "", "monthly": u["monthly"], "limit": limit}
    if not u["ok"]:
        out["reason"] = f"spend not checked ({u['error']})"
        return out
    if u["limit_remaining"] is not None and float(u["limit_remaining"]) <= 0:
        out.update(allowed=False, reason="the OpenRouter key's own credit limit is used up")
    elif limit and u["monthly"] >= limit:
        out.update(allowed=False, reason=f"this month's spend ${u['monthly']:.2f} reached your limit ${limit:.2f} "
                                         f"(MONTHLY_SPEND_LIMIT_USD in brain/.env; 0 turns the guard off)")
    return out


def require() -> None:
    c = check()
    if not c["allowed"]:
        raise BudgetExceeded("Stopped to protect your credits: " + c["reason"])
