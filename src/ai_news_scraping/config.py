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

    brave_search_api_key: str

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    gmail_user: str
    gmail_app_password: str

    supabase_url: str
    supabase_service_role_key: str
    supabase_schema: str = "ai_news"

    admin_token: str
    # False 면 admin 페이지의 HTTPBasic 인증을 완전 우회. 로컬 전용일 때만.
    admin_auth_enabled: bool = True

    dry_run: bool = False
    digest_tz: str = "Asia/Seoul"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
