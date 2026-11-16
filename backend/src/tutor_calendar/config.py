from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from ``TC_*`` environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="TC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tutor:tutor@localhost:5432/tutor_calendar"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Where the web app is served. Sign-in links point here.
    public_url: str = "http://localhost:5173"
    # Session cookies are marked Secure. Browsers still accept them on
    # http://localhost, so this only needs turning off for plain-HTTP hosts.
    cookie_secure: bool = True
    # For a public demonstration: anyone may enter the demo tutor's panel
    # without a sign-in link, and sample activity is created. Never set this
    # on an installation that holds real students.
    demo_mode: bool = False
    # A folder with the built web app. When set, the API serves it too, which
    # is how production runs: one process, one origin.
    static_dir: Path | None = None
    # Signs the links students use to manage a booking. Without it a random
    # one is made up at start, and links stop working when the process restarts.
    secret_key: str | None = None

    # Outgoing mail. Without a host, the worker writes messages to its log.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    mail_from: str = "Tutor Calendar <no-reply@localhost>"
    # How often the worker looks for lessons to charge and mail to send.
    worker_interval_seconds: float = 30.0
