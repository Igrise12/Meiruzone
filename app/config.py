"""Backend-only configuration; mailbox secrets are never API settings."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    database_path: Path = Path("data/meiruzone.sqlite3")
    demo: bool = False
    review_threshold: float = Field(default=70, ge=0, le=100)
    frontend_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @field_validator("frontend_origins")
    @classmethod
    def validate_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username is not None
                or url.password is not None
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("Frontend origins must be explicit loopback origins.")
            _ = url.port  # Validate the port as well as the hostname.
        return origins

    @classmethod
    def from_env(cls) -> "Settings":
        values = {}
        for field, variable in (
            ("database_path", "MEIRUZONE_DATABASE_PATH"),
            ("demo", "MEIRUZONE_DEMO"),
            ("review_threshold", "MEIRUZONE_REVIEW_THRESHOLD"),
        ):
            if variable in os.environ:
                values[field] = os.environ[variable]
        if "MEIRUZONE_FRONTEND_ORIGINS" in os.environ:
            values["frontend_origins"] = tuple(
                origin.strip()
                for origin in os.environ["MEIRUZONE_FRONTEND_ORIGINS"].split(",")
            )
        return cls.model_validate(values)
