from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tutor_calendar.logs import LogFormat


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
    # How often one visitor may call the API. Only worth turning off for a
    # load test, which is a single visitor by design.
    rate_limits: bool = True
    # The header in which the proxy in front of this process puts the
    # visitor's address, for example CF-Connecting-IP or X-Real-IP. Without
    # it visitors are told apart by the address of the connection, which
    # behind a proxy is the same for all of them. Only set it when nothing
    # can reach this process except through the proxy: anyone else could
    # write the header themselves.
    client_address_header: str | None = None
    # Signs the links students use to manage a booking. Without it a random
    # one is made up at start, and links stop working when the process restarts.
    secret_key: str | None = None

    # Whoever sends this as a bearer token may read /metrics. Without it the
    # endpoint answers 404: the application's port may be open to everyone,
    # and nothing else guards it. See ADR 0011.
    metrics_token: str | None = None
    # "json" is one object per line, for a machine to read. "text" is for a
    # person watching a terminal.
    log_format: LogFormat = "json"

    # Outgoing mail. Without a host, the worker writes messages to its log.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    mail_from: str = "Tutor Calendar <no-reply@localhost>"
    # How often the worker looks for lessons to charge and mail to send.
    worker_interval_seconds: float = 30.0

    @field_validator("metrics_token")
    @classmethod
    def _a_long_token_or_none(cls, value: str | None) -> str | None:
        if not value:
            # Compose passes an unset variable on as an empty one.
            return None
        if len(value) < 32:
            # Nothing limits how often the endpoint may be tried, so the
            # token has to be too long to guess.
            raise ValueError("must be at least 32 characters")
        return value
