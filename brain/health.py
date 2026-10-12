"""OpenRouter health check. Run: python -m brain.health  (exit 0 = OK, 1 = not OK)."""
import os
import sys
import time
from pathlib import Path

# Allow running as a plain script from any folder (python3 brain/health.py ...):
# put the repo root on sys.path and re-launch inside the repo venv if we're on system Python.
_ROOT = Path(__file__).resolve().parent.parent
_VENV_PY = _ROOT / "venv" / "bin" / "python"
if __name__ == "__main__":
    sys.path.insert(0, str(_ROOT))
    if _VENV_PY.exists() and sys.prefix == sys.base_prefix:
        os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

import requests  # noqa: E402

from brain import config, llm  # noqa: E402


def check() -> dict:
    res = {"ok": False, "key_valid": False, "model_used": None, "latency_s": None, "error": None}
    try:
        key = config.api_key()
    except RuntimeError as e:
        res["error"] = str(e)
        return res
    try:
        r = requests.get(f"{config.OPENROUTER_BASE}/auth/key",
                         headers={"Authorization": f"Bearer {key}"}, timeout=20)
        res["key_valid"] = r.status_code == 200
        if not res["key_valid"]:
            res["error"] = f"Key rejected by OpenRouter (HTTP {r.status_code})"
            return res
    except requests.RequestException as e:
        res["error"] = f"Cannot reach OpenRouter: {e}"
        return res
    t0 = time.time()
    try:
        text, model = llm.chat([{"role": "user", "content": "Reply with exactly: OK"}],
                               max_tokens=512, timeout=45, backoff=0.5)
        res.update(ok=True, model_used=model, latency_s=round(time.time() - t0, 2))
    except llm.LLMUnavailable as e:
        res["error"] = str(e)
    return res


def select_cli() -> int:
    """python -m brain.health --select : probe models one by one, print table, pick first working."""
    def show(r):
        mark = "OK  " if r["ok"] else "FAIL"
        print(f"  [{r['tier']:4}] {mark} {r['model']}  {r['latency_s']}s  {r['error'] or ''}", flush=True)

    print("Probing free models in order, then paid only if all free fail...")
    try:
        sel = llm.select_model(force=True, on_result=show)
    except llm.LLMUnavailable:
        print("NO MODEL AVAILABLE (free and paid tiers all failed)")
        return 1
    print(f"SELECTED {sel['model']} ({sel['tier']} tier)")
    return 0


def main() -> int:
    if "--select" in sys.argv:
        return select_cli()
    r = check()
    if r["ok"]:
        print(f"OK model={r['model_used']} latency={r['latency_s']}s")
        return 0
    print(f"FAIL {r['error']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
