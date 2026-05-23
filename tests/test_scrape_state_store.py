from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_news_scraping.scrape_state_store import (
    InMemoryScrapeStateStore,
    SupabaseScrapeStateStore,
)

# ────────── InMemoryScrapeStateStore ──────────


def test_in_memory_default_enabled() -> None:
    store = InMemoryScrapeStateStore()
    assert store.is_enabled() is True


def test_in_memory_initial_false() -> None:
    store = InMemoryScrapeStateStore(initial=False)
    assert store.is_enabled() is False


def test_in_memory_set_enabled() -> None:
    store = InMemoryScrapeStateStore()
    store.set_enabled(False)
    assert store.is_enabled() is False


def test_in_memory_toggle_round_trip() -> None:
    store = InMemoryScrapeStateStore(initial=True)
    assert store.toggle() is False
    assert store.is_enabled() is False
    assert store.toggle() is True
    assert store.is_enabled() is True


# ────────── SupabaseScrapeStateStore — fluent mock ──────────


@dataclass
class FakeResp:
    data: Any = None


@dataclass
class FakeQuery:
    selected: tuple[str, ...] = ()
    eq_col: str | None = None
    eq_val: Any = None
    single_called: bool = False
    updated: dict[str, Any] | None = None
    resp_data: Any = None

    def select(self, *cols: str) -> FakeQuery:
        self.selected = cols
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        self.eq_col = col
        self.eq_val = val
        return self

    def single(self) -> FakeQuery:
        self.single_called = True
        return self

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.updated = payload
        return self

    def execute(self) -> FakeResp:
        return FakeResp(data=self.resp_data)


@dataclass
class FakeClient:
    table_name: str | None = None
    queries: list[FakeQuery] = field(default_factory=list)
    response_queue: list[Any] = field(default_factory=list)

    def table(self, name: str) -> FakeQuery:
        self.table_name = name
        q = FakeQuery()
        if self.response_queue:
            q.resp_data = self.response_queue.pop(0)
        self.queries.append(q)
        return q


def test_supabase_is_enabled_reads_singleton_row() -> None:
    fake = FakeClient(response_queue=[{"enabled": False}])
    store = SupabaseScrapeStateStore(fake)
    assert store.is_enabled() is False
    q = fake.queries[0]
    assert fake.table_name == "scrape_enabled"
    assert q.selected == ("enabled",)
    assert q.eq_col == "id"
    assert q.eq_val == 1
    assert q.single_called is True


def test_supabase_is_enabled_defaults_to_true_on_missing_data() -> None:
    fake = FakeClient(response_queue=[None])
    store = SupabaseScrapeStateStore(fake)
    assert store.is_enabled() is True


def test_supabase_set_enabled_writes_update_with_timestamp() -> None:
    fake = FakeClient(response_queue=[None])
    store = SupabaseScrapeStateStore(fake)
    store.set_enabled(False)
    q = fake.queries[0]
    assert q.updated is not None
    assert q.updated["enabled"] is False
    assert "updated_at" in q.updated
    assert q.eq_col == "id"
    assert q.eq_val == 1


def test_supabase_toggle_inverts_current_state() -> None:
    fake = FakeClient(response_queue=[{"enabled": True}, None])
    store = SupabaseScrapeStateStore(fake)
    assert store.toggle() is False
    assert len(fake.queries) == 2  # is_enabled + set_enabled
