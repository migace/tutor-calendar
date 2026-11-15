from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from ``TC_*`` environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="TC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tutor:tutor@localhost:5432/tutor_calendar"
    cors_origins: list[str] = ["http://localhost:5173"]
