from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from disclosure_impact_agent.environment import load_project_environment


load_project_environment()


class Settings(BaseModel):
    """Validated runtime settings with safe offline defaults."""

    model_config = ConfigDict(frozen=True)

    data_mode: Literal["fixture", "dart"] = "fixture"
    llm_mode: Literal["fake", "openai"] = "fake"
    openai_model: str | None = None
    max_memo_chars: int = Field(default=5_000, ge=1, le=100_000)
    llm_timeout_seconds: float = Field(default=30, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    @classmethod
    def from_environment(cls) -> "Settings":
        values = {
            "data_mode": os.getenv("DATA_MODE", "fixture").lower(),
            "llm_mode": os.getenv("LLM_MODE", "fake").lower(),
            "openai_model": os.getenv("OPENAI_MODEL") or None,
            "max_memo_chars": os.getenv("MAX_MEMO_CHARS", "5000"),
            "llm_timeout_seconds": os.getenv("LLM_TIMEOUT_SECONDS", "30"),
            "llm_max_retries": os.getenv("LLM_MAX_RETRIES", "2"),
        }
        settings = cls.model_validate(values)
        if settings.llm_mode == "openai" and not settings.openai_model:
            raise ValueError("OPENAI_MODEL is required when LLM_MODE=openai")
        return settings


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings.from_environment()
    except ValidationError as exc:
        raise RuntimeError(f"Invalid runtime configuration: {exc}") from exc
