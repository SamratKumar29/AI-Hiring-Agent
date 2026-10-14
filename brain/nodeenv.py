"""Find a Node.js >= 22 binary even when nvm is not loaded (cron, the UI, subprocesses)."""
import os
import re
import shutil
import subprocess
from pathlib import Path

MIN_MAJOR = 22


def _major(node: str) -> int:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(re.match(r"v(\d+)", out.strip()).group(1))
    except Exception:  # noqa: BLE001
        return 0


def node_bin() -> str | None:
    """Path to node >= MIN_MAJOR, or None."""
    cands = []
    w = shutil.which("node")
    if w:
        cands.append(w)
    root = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm")) / "versions" / "node"
    if root.exists():
        cands += [str(p / "bin" / "node") for p in sorted(root.iterdir(), key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)], reverse=True)]
    for c in cands:
        if Path(c).exists() and _major(c) >= MIN_MAJOR:
            return c
    return None


PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def with_proxy_support(env: dict) -> dict:
    """Node's fetch ignores HTTP(S)_PROXY unless NODE_USE_ENV_PROXY=1 (needed behind office proxies and in cron)."""
    if any(env.get(v) for v in PROXY_VARS):
        env.setdefault("NODE_USE_ENV_PROXY", "1")
    return env


def env_with_node() -> dict:
    """os.environ with node's folder first on PATH (so `npx`/child node calls match)."""
    nb = node_bin()
    env = with_proxy_support(dict(os.environ))
    if nb:
        env["PATH"] = str(Path(nb).parent) + os.pathsep + env.get("PATH", "")
    return env
