"""Scrape ON/OFF singleton state store.

Admin 의 토글 버튼과 cron 직전 게이트 (run() 호출 전 체크) 의 공용
인터페이스. Supabase 스키마의 ``scrape_enabled`` 싱글톤 행 (id=1) 을 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol


class ScrapeStateStore(Protocol):
    def is_enabled(self) -> bool: ...
    def set_enabled(self, enabled: bool) -> None: ...
    def toggle(self) -> bool: ...


class InMemoryScrapeStateStore:
    def __init__(self, initial: bool = True) -> None:
        self._enabled = initial

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def toggle(self) -> bool:
        self._enabled = not self._enabled
        return self._enabled


class SupabaseScrapeStateStore:
    SINGLETON_ID = 1

    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self, name: str) -> Any:
        return self._client.schema(self._schema).table(name)

    def is_enabled(self) -> bool:
        resp = (
            self._table("scrape_enabled")
            .select("enabled")
            .eq("id", self.SINGLETON_ID)
            .single()
            .execute()
        )
        data = getattr(resp, "data", None) or {}
        return bool(data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        (
            self._table("scrape_enabled")
            .update({
                "enabled": enabled,
                "updated_at": datetime.now(UTC).isoformat(),
            })
            .eq("id", self.SINGLETON_ID)
            .execute()
        )

    def toggle(self) -> bool:
        new_state = not self.is_enabled()
        self.set_enabled(new_state)
        return new_state
