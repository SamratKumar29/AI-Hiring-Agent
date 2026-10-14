"""Central settings. The ONLY secrets file is brain/.env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BRAIN_DIR = Path(__file__).resolve().parent
ROOT_DIR = BRAIN_DIR.parent
DATA_DIR = BRAIN_DIR / "data"
ENV_FILE = BRAIN_DIR / ".env"

load_dotenv(ENV_FILE)


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def api_key() -> str:
    key = _get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is empty. Copy brain/.env.example to brain/.env and paste your key."
        )
    return key


def _split(name: str) -> list[str]:
    return [m.strip() for m in _get(name).split(",") if m.strip()]


def free_models() -> list[str]:
    """Tier 1: OPENROUTER_MODELS, ordered by thinking capability (best first)."""
    return _split("OPENROUTER_MODELS")


def paid_models() -> list[str]:
    """Tier 2: OPENROUTER_PAID_FALLBACK, used only when every free model fails."""
    free = set(free_models())
    return [m for m in _split("OPENROUTER_PAID_FALLBACK") if m not in free]


def models() -> list[str]:
    """Free tier first, then paid tier."""
    return free_models() + paid_models()


def get(name: str, default: str = "") -> str:
    return _get(name, default)


OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def set_env_value(name: str, value: str) -> None:
    """Set NAME=value in brain/.env in place (keeps every other line and comment), file mode 600."""
    if "\n" in value or "\r" in value:
        raise ValueError("value must be a single line")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for i, ln in enumerate(lines):
        if ln.split("=", 1)[0].strip() == name:
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    tmp = ENV_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(ENV_FILE)
    os.environ[name] = value


def save_env(updates: dict) -> None:
    """Set several NAME=value pairs in brain/.env at once (comments and file mode 600 are kept; empty value = clear)."""
    for k, v in updates.items():
        set_env_value(k, "" if v is None else str(v).strip())
