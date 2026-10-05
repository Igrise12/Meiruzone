"""Backend-only configuration; mailbox secrets are never API settings."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    database_path: Path = Path("data/meiruzone.sqlite3")
    demo: bool = False
    model_directory: Path | None = Field(default=None, repr=False)
    review_threshold: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    frontend_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    imap_host: str | None = Field(default=None, max_length=253, repr=False)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_username: str | None = Field(default=None, max_length=320, repr=False)
    imap_password: SecretStr | None = Field(default=None, exclude=True, repr=False)
    imap_mailbox: str = Field(default="INBOX", min_length=1, max_length=1024, repr=False)

    @field_validator("imap_host", "imap_username", "imap_mailbox")
    @classmethod
    def validate_imap_text(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("IMAP configuration cannot contain control characters.")
        return value

    @field_validator("imap_host")
    @classmethod
    def validate_imap_host(cls, value: str | None) -> str | None:
        if not value:
            return None
        if any(character.isspace() or character in "/\\@?#" for character in value):
            raise ValueError("IMAP host must be a hostname or IP address, without a URL.")
        return value.lower()

    @field_validator("imap_mailbox")
    @classmethod
    def normalize_inbox(cls, value: str) -> str:
        return "INBOX" if value.casefold() == "inbox" else value

    @field_validator("imap_password")
    @classmethod
    def validate_imap_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and any(ord(character) < 32 or ord(character) == 127
                                     for character in value.get_secret_value()):
            raise ValueError("IMAP passwords cannot contain control characters.")
        return value

    @property
    def imap_available(self) -> bool:
        return bool(self.imap_host and self.imap_username and self.imap_password
                    and self.imap_password.get_secret_value())

    @property
    def imap_account_key(self) -> str:
        # Scope identifiers contain no password and do not expose a login address.
        identity = json.dumps([self.imap_host, self.imap_port, self.imap_username])
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

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
            ("model_directory", "MEIRUZONE_MODEL_DIRECTORY"),
            ("review_threshold", "MEIRUZONE_REVIEW_THRESHOLD"),
            ("imap_host", "MEIRUZONE_IMAP_HOST"),
            ("imap_port", "MEIRUZONE_IMAP_PORT"),
            ("imap_username", "MEIRUZONE_IMAP_USERNAME"),
            ("imap_password", "MEIRUZONE_IMAP_PASSWORD"),
            ("imap_mailbox", "MEIRUZONE_IMAP_MAILBOX"),
        ):
            if variable in os.environ:
                values[field] = os.environ[variable]
        if "MEIRUZONE_FRONTEND_ORIGINS" in os.environ:
            values["frontend_origins"] = tuple(
                origin.strip()
                for origin in os.environ["MEIRUZONE_FRONTEND_ORIGINS"].split(",")
            )
        return cls.model_validate(values)
