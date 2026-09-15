from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_environment() -> bool:
    """Load a local project .env without replacing shell-provided values."""
    return load_dotenv(PROJECT_ROOT / ".env", override=False)

