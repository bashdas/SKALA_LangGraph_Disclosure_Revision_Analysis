import pytest

from disclosure_impact_agent.config import Settings


def test_openai_mode_requires_explicit_model(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        Settings.from_environment()


def test_invalid_data_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "unknown")

    with pytest.raises(Exception):
        Settings.from_environment()

