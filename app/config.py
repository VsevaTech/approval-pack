"""Application settings, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every value has a safe default so the app boots with no .env at all.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APPROVAL_PACK_",
        extra="ignore",
    )

    app_name: str = "Approval Pack"
    base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL used to render review links.",
    )
    database_url: str = "sqlite:///./data/approval_pack.db"
    storage_dir: Path = Path("./data/snapshots")

    #: Maximum accepted upload size in bytes (default 5 MiB).
    max_upload_bytes: int = 5 * 1024 * 1024
    #: Maximum accepted inline snapshot text length in characters.
    max_text_chars: int = 200_000

    #: Number of random bytes behind a review token (32 bytes == 256 bits).
    review_token_bytes: int = 32

    #: Optional shared password protecting the owner area. Empty == open (dev).
    owner_password: str = ""
    #: Secret used to sign the owner session cookie.
    secret_key: str = "dev-insecure-secret-change-me"

    debug: bool = False

    @property
    def owner_area_protected(self) -> bool:
        return bool(self.owner_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
