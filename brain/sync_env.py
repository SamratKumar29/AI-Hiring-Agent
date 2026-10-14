"""Export the central key under every variable name the subprojects expect."""
import os
import subprocess

from brain import config, nodeenv


def export_env(probe: bool = True) -> dict:
    """probe=True picks the first model that is answering right now (not flooded)."""
    from brain import llm

    key = config.api_key()
    first = llm.healthy_model() if probe else config.models()[0]
    return {
        "OPENROUTER_API_KEY": key,
        "OPENAI_BASE_URL": config.OPENROUTER_BASE,
        "OPENAI_API_KEY": key,
        "OPENAI_MODEL": first,
        "CAREER_OPS_MODEL": first,
        "LLM_PROVIDER": "openrouter",
        "LLM_MODEL": f"openrouter/{first}",
        "LLM_API_KEY": key,
        "LLM_API_BASE": config.OPENROUTER_BASE,
        "CAREER_OPS_MODEL_TIMEOUT_MS": "240000",
        "FIRECRAWL_API_KEY": config.get("FIRECRAWL_API_KEY"),
    }


def run_with_env(cmd: list, cwd: str, **kwargs) -> subprocess.CompletedProcess:
    env = nodeenv.with_proxy_support({**os.environ, **{k: v for k, v in export_env().items() if v}})
    return subprocess.run(cmd, cwd=cwd, env=env, **kwargs)


MODEL_FAIL_MARKERS = ("OpenRouter error", "Empty response", "HTTP 429", "HTTP 402", "timed out",
                      "rate-limited", "API error", "empty response")


def run_with_fallback(cmd: list, cwd: str, timeout: int = 900, models: list | None = None, validate=None):
    """Run a subproject command pinned to each model in turn until one succeeds.

    For tools that accept only ONE model (career-ops runners, openai-eval).
    `validate(proc, model)` (optional) may return an error string to REJECT a run that exited cleanly but produced
    nothing usable (e.g. a model that answered with a tool call instead of an evaluation) -> next model is tried.
    Returns (CompletedProcess, model_used). Raises LLMUnavailable if all fail.
    """
    from brain.llm import LLMUnavailable

    errors: dict = {}
    base = {k: v for k, v in export_env(probe=False).items() if v}
    for m in models or [x for x in config.models() if not x.endswith(":batch")]:
        env = nodeenv.with_proxy_support({**os.environ, **base, "CAREER_OPS_MODEL": m, "OPENAI_MODEL": m,
                                          "LLM_MODEL": f"openrouter/{m}"})
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            errors[m] = "timeout"
            continue
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and not any(x in out for x in MODEL_FAIL_MARKERS):
            bad = validate(r, m) if validate else None
            if not bad:
                return r, m
            errors[m] = str(bad)[:120]
            continue
        errors[m] = next((ln.strip()[:120] for ln in out.splitlines()
                          if any(x in ln for x in MODEL_FAIL_MARKERS)), f"exit {r.returncode}")
        errors[m] = errors[m].replace(base["OPENROUTER_API_KEY"], "***")
    raise LLMUnavailable(errors)
