from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ai_news_scraping.run_store import (
    InMemoryRunStore,
    RunRecord,
    SupabaseRunStore,
)

# ════════════════════ InMemoryRunStore ════════════════════


def test_start_run_creates_running_record() -> None:
    s = InMemoryRunStore()
    r = s.start_run()
    assert r.status == "running"
    assert r.article_count == 0
    assert r.finished_at is None
    assert r.run_id
    # 같은 호출이라도 다른 run_id
    assert s.start_run().run_id != r.run_id


def test_mark_finished_updates_record() -> None:
    s = InMemoryRunStore()
    r = s.start_run()
    s.mark_finished(r.run_id, status="success", article_count=15, digest_text="ok")
    rec = s.list_recent()[0]
    assert rec.status == "success"
    assert rec.article_count == 15
    assert rec.digest_text == "ok"
    assert rec.finished_at is not None


def test_mark_finished_with_error() -> None:
    s = InMemoryRunStore()
    r = s.start_run()
    s.mark_finished(r.run_id, status="failed", article_count=0, error="brave 500")
    rec = s.list_recent()[0]
    assert rec.status == "failed"
    assert rec.error == "brave 500"


def test_mark_finished_invalid_status_raises() -> None:
    s = InMemoryRunStore()
    r = s.start_run()
    with pytest.raises(ValueError, match="status"):
        s.mark_finished(r.run_id, status="weird")


def test_mark_finished_unknown_run_raises() -> None:
    s = InMemoryRunStore()
    with pytest.raises(KeyError):
        s.mark_finished("no-such-id", status="success")


def test_list_recent_orders_by_started_at_desc() -> None:
    counter = [datetime(2026, 5, 23, 0, 0, 0, tzinfo=UTC)]

    def now_fn() -> datetime:
        counter[0] += timedelta(seconds=1)
        return counter[0]

    s = InMemoryRunStore(now_fn=now_fn)
    s.start_run()
    s.start_run()
    s.start_run()
    recent = s.list_recent(limit=2)
    assert len(recent) == 2
    # 최신 것이 먼저
    assert recent[0].started_at > recent[1].started_at


def test_get_last_success_skips_failed_and_running() -> None:
    counter = [datetime(2026, 5, 23, 0, 0, 0, tzinfo=UTC)]

    def now_fn() -> datetime:
        counter[0] += timedelta(seconds=1)
        return counter[0]

    s = InMemoryRunStore(now_fn=now_fn)
    r1 = s.start_run()
    s.mark_finished(r1.run_id, status="success", article_count=10)
    r2 = s.start_run()
    s.mark_finished(r2.run_id, status="failed", article_count=0, error="boom")
    r3 = s.start_run()  # 아직 running

    last = s.get_last_success()
    assert last is not None
    assert last.run_id == r1.run_id
    assert r3 is not None


def test_get_last_success_returns_none_when_no_success() -> None:
    s = InMemoryRunStore()
    r = s.start_run()
    s.mark_finished(r.run_id, status="failed")
    assert s.get_last_success() is None


# ════════════════════ SupabaseRunStore — fluent mock ════════════════════


@dataclass
class FakeResp:
    data: Any = None


@dataclass
class FakeQuery:
    inserted: Any = None
    updated: dict[str, Any] | None = None
    selected: tuple[str, ...] = ()
    eq_col: str | None = None
    eq_val: Any = None
    ordered: tuple[str, bool] | None = None
    limited: int | None = None
    resp_data: Any = None

    def insert(self, payload: Any) -> FakeQuery:
        self.inserted = payload
        return self

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.updated = payload
        return self

    def select(self, *cols: str) -> FakeQuery:
        self.selected = cols
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        self.eq_col = col
        self.eq_val = val
        return self

    def order(self, col: str, *, desc: bool = False) -> FakeQuery:
        self.ordered = (col, desc)
        return self

    def limit(self, n: int) -> FakeQuery:
        self.limited = n
        return self

    def execute(self) -> FakeResp:
        return FakeResp(data=self.resp_data)


@dataclass
class FakeClient:
    table_name: str | None = None
    schema_name: str | None = None
    queries: list[FakeQuery] = field(default_factory=list)
    response_queue: list[Any] = field(default_factory=list)

    def schema(self, name: str) -> FakeClient:
        self.schema_name = name
        return self

    def table(self, name: str) -> FakeQuery:
        self.table_name = name
        q = FakeQuery()
        if self.response_queue:
            q.resp_data = self.response_queue.pop(0)
        self.queries.append(q)
        return q


def test_supabase_start_run_inserts_payload() -> None:
    fake = FakeClient(response_queue=[None])
    s = SupabaseRunStore(fake)
    r = s.start_run()
    assert r.status == "running"
    payload = fake.queries[0].inserted
    assert payload["run_id"] == r.run_id
    assert payload["status"] == "running"
    assert "started_at" in payload
    assert fake.schema_name == "ai_news"
    assert fake.table_name == "runs"


def test_supabase_mark_finished_updates_payload() -> None:
    fake = FakeClient(response_queue=[None])
    s = SupabaseRunStore(fake)
    s.mark_finished("rid", status="success", article_count=8, digest_text="md")
    q = fake.queries[0]
    assert q.updated is not None
    assert q.updated["status"] == "success"
    assert q.updated["article_count"] == 8
    assert q.updated["digest_text"] == "md"
    assert "finished_at" in q.updated
    assert q.eq_col == "run_id"
    assert q.eq_val == "rid"


def test_supabase_mark_finished_invalid_status_short_circuits() -> None:
    fake = FakeClient()
    s = SupabaseRunStore(fake)
    with pytest.raises(ValueError):
        s.mark_finished("rid", status="bad")
    assert fake.queries == []


def test_supabase_list_recent() -> None:
    rows = [
        {
            "run_id": "r1",
            "started_at": "2026-05-23T09:00:00+00:00",
            "finished_at": "2026-05-23T09:01:00+00:00",
            "status": "success",
            "article_count": 10,
        },
        {
            "run_id": "r2",
            "started_at": "2026-05-22T09:00:00+00:00",
            "finished_at": None,
            "status": "failed",
            "article_count": 0,
            "error": "boom",
        },
    ]
    fake = FakeClient(response_queue=[rows])
    s = SupabaseRunStore(fake)
    recs = s.list_recent(limit=10)
    assert len(recs) == 2
    assert recs[0].run_id == "r1"
    assert recs[0].article_count == 10
    assert recs[1].error == "boom"
    assert fake.queries[0].ordered == ("started_at", True)
    assert fake.queries[0].limited == 10


def test_supabase_get_last_success_returns_record() -> None:
    rows = [{
        "run_id": "r1",
        "started_at": "2026-05-23T09:00:00+00:00",
        "finished_at": "2026-05-23T09:01:00+00:00",
        "status": "success",
        "article_count": 12,
    }]
    fake = FakeClient(response_queue=[rows])
    s = SupabaseRunStore(fake)
    rec = s.get_last_success()
    assert rec is not None
    assert rec.run_id == "r1"
    assert fake.queries[0].eq_col == "status"
    assert fake.queries[0].eq_val == "success"


def test_supabase_get_last_success_returns_none_when_empty() -> None:
    fake = FakeClient(response_queue=[[]])
    s = SupabaseRunStore(fake)
    assert s.get_last_success() is None


def test_run_record_default_fields() -> None:
    r = RunRecord(run_id="x", started_at=datetime.now(UTC))
    assert r.status == "running"
    assert r.article_count == 0
    assert r.finished_at is None
    assert r.error is None
