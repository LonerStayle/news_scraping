from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ai_news_scraping.subscriber_store import (
    InMemorySubscriberStore,
    Subscriber,
    SupabaseSubscriberStore,
)

# ────────── InMemorySubscriberStore ──────────


def test_in_memory_starts_empty() -> None:
    store = InMemorySubscriberStore()
    assert store.list_all() == []
    assert store.list_active_emails() == []


def test_in_memory_add_basic() -> None:
    store = InMemorySubscriberStore()
    sub = store.add("a@x.com")
    assert sub == Subscriber(id=1, email="a@x.com", active=True)
    assert store.list_active_emails() == ["a@x.com"]


def test_in_memory_add_strips_whitespace() -> None:
    store = InMemorySubscriberStore()
    sub = store.add("  a@x.com  ")
    assert sub.email == "a@x.com"


def test_in_memory_add_dedups_by_email() -> None:
    store = InMemorySubscriberStore()
    a = store.add("a@x.com")
    a_again = store.add("a@x.com")
    assert a == a_again
    assert len(store.list_all()) == 1


def test_in_memory_remove() -> None:
    store = InMemorySubscriberStore()
    sub = store.add("a@x.com")
    assert store.remove(sub.id) is True
    assert store.list_all() == []


def test_in_memory_remove_missing_id_returns_false() -> None:
    store = InMemorySubscriberStore()
    assert store.remove(999) is False


@pytest.mark.parametrize("bad", ["", "  ", "no-at-sign", "x@", "@x.com", "x@host-no-dot"])
def test_in_memory_invalid_email_raises(bad: str) -> None:
    store = InMemorySubscriberStore()
    with pytest.raises(ValueError, match="invalid email"):
        store.add(bad)


# ────────── SupabaseSubscriberStore — fluent mock ──────────


@dataclass
class FakeResp:
    data: Any = None


@dataclass
class FakeQuery:
    selected: tuple[str, ...] = ()
    eq_col: str | None = None
    eq_val: Any = None
    ordered: str | None = None
    upserted: dict[str, Any] | None = None
    upsert_on_conflict: str | None = None
    deleted: bool = False
    resp_data: Any = None

    def select(self, *cols: str) -> FakeQuery:
        self.selected = cols
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        self.eq_col = col
        self.eq_val = val
        return self

    def order(self, col: str) -> FakeQuery:
        self.ordered = col
        return self

    def upsert(
        self, payload: dict[str, Any], *, on_conflict: str | None = None
    ) -> FakeQuery:
        self.upserted = payload
        self.upsert_on_conflict = on_conflict
        return self

    def delete(self) -> FakeQuery:
        self.deleted = True
        return self

    def execute(self) -> FakeResp:
        return FakeResp(data=self.resp_data)


@dataclass
class FakeClient:
    table_name: str | None = None
    schema_name: str | None = None
    query: FakeQuery = field(default_factory=FakeQuery)

    def schema(self, name: str) -> FakeClient:
        self.schema_name = name
        return self

    def table(self, name: str) -> FakeQuery:
        self.table_name = name
        return self.query


def test_supabase_list_active_emails() -> None:
    fake = FakeClient(query=FakeQuery(resp_data=[{"email": "a@x.com"}, {"email": "b@x.com"}]))
    store = SupabaseSubscriberStore(fake)
    assert store.list_active_emails() == ["a@x.com", "b@x.com"]
    assert fake.table_name == "subscribers"
    assert fake.query.eq_col == "active"
    assert fake.query.eq_val is True


def test_supabase_list_all_orders_by_id() -> None:
    fake = FakeClient(
        query=FakeQuery(
            resp_data=[
                {"id": 1, "email": "a@x.com", "active": True},
                {"id": 2, "email": "b@x.com", "active": False},
            ]
        )
    )
    store = SupabaseSubscriberStore(fake)
    subs = store.list_all()
    assert len(subs) == 2
    assert subs[1] == Subscriber(id=2, email="b@x.com", active=False)
    assert fake.query.ordered == "id"


def test_supabase_add_upserts_with_on_conflict() -> None:
    fake = FakeClient(query=FakeQuery(resp_data=[{"id": 7, "email": "a@x.com", "active": True}]))
    store = SupabaseSubscriberStore(fake)
    result = store.add("a@x.com")
    assert result == Subscriber(id=7, email="a@x.com", active=True)
    assert fake.query.upserted == {"email": "a@x.com", "active": True}
    assert fake.query.upsert_on_conflict == "email"


def test_supabase_add_invalid_email_raises_before_call() -> None:
    fake = FakeClient()
    store = SupabaseSubscriberStore(fake)
    with pytest.raises(ValueError):
        store.add("not-an-email")
    assert fake.table_name is None


def test_supabase_remove_returns_true_when_rows_deleted() -> None:
    fake = FakeClient(query=FakeQuery(resp_data=[{"id": 3}]))
    store = SupabaseSubscriberStore(fake)
    assert store.remove(3) is True
    assert fake.query.deleted is True
    assert fake.query.eq_col == "id"
    assert fake.query.eq_val == 3


def test_supabase_remove_returns_false_when_no_rows() -> None:
    fake = FakeClient(query=FakeQuery(resp_data=[]))
    store = SupabaseSubscriberStore(fake)
    assert store.remove(999) is False
