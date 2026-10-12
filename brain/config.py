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
