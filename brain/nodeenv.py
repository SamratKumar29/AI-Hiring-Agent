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


def env_with_node() -> dict:
    """os.environ with node's folder first on PATH (so `npx`/child node calls match)."""
    nb = node_bin()
    env = dict(os.environ)
    if nb:
        env["PATH"] = str(Path(nb).parent) + os.pathsep + env.get("PATH", "")
    return env
