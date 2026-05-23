from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_news_scraping.config import Settings, get_settings

REQUIRED_ENV = {
    "GOOGLE_CSE_API_KEY": "k1",
    "GOOGLE_CSE_CX": "cx1",
    "GEMINI_API_KEY": "g1",
    "GMAIL_USER": "sender@example.com",
    "GMAIL_APP_PASSWORD": "p1",
    "SUPABASE_URL": "https://x.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "s1",
    "ADMIN_TOKEN": "t1",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str] | None = None) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    for k, v in (overrides or {}).items():
        monkeypatch.setenv(k, v)


def test_settings_loads_required_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.google_cse_api_key == "k1"
    assert s.gmail_user == "sender@example.com"
    assert s.supabase_url == "https://x.supabase.co"


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.gemini_model == "gemini-2.5-flash"
    assert s.dry_run is False
    assert s.digest_tz == "Asia/Seoul"


def test_settings_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, {"GEMINI_MODEL": "gemini-2.5-pro", "DRY_RUN": "true"})
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.gemini_model == "gemini-2.5-pro"
    assert s.dry_run is True


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()


def test_settings_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
