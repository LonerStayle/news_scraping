"""Typed environment-variable loader (pydantic-settings).

All secrets and runtime flags come from `.env` (local dev) or the process
environment (CI / GitHub Actions). Importing `get_settings()` once at the
top of an entry point gives a frozen Settings instance.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    google_cse_api_key: str
    google_cse_cx: str

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    gmail_user: str
    gmail_app_password: str

    supabase_url: str
    supabase_service_role_key: str
    supabase_schema: str = "ai_news"

    admin_token: str

    dry_run: bool = False
    digest_tz: str = "Asia/Seoul"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
