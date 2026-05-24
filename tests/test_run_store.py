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
    gte_col: str | None = None
    gte_val: Any = None
    lt_col: str | None = None
    lt_val: Any = None
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

    def gte(self, col: str, val: Any) -> FakeQuery:
        self.gte_col = col
        self.gte_val = val
        return self

    def lt(self, col: str, val: Any) -> FakeQuery:
        self.lt_col = col
        self.lt_val = val
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


# ════════════════════ has_success_today ════════════════════

from zoneinfo import ZoneInfo  # noqa: E402

KST = ZoneInfo("Asia/Seoul")


def _fixed_now_fn(fixed_kst: datetime) -> Any:
    fixed_utc = fixed_kst.astimezone(UTC)
    return lambda: fixed_utc


def test_has_success_today_returns_false_when_empty() -> None:
    s = InMemoryRunStore()
    now_kst = datetime(2026, 5, 24, 10, 0, tzinfo=KST)
    assert s.has_success_today(now_kst) is False


def test_has_success_today_true_when_today_success_exists() -> None:
    # finished_at = 2026-05-24 09:15 KST (UTC 00:15)
    fixed_kst = datetime(2026, 5, 24, 9, 15, tzinfo=KST)
    s = InMemoryRunStore(now_fn=_fixed_now_fn(fixed_kst))
    r = s.start_run()
    s.mark_finished(r.run_id, status="success", article_count=5)
    # 같은 날 KST 의 다른 시각으로 조회
    query_kst = datetime(2026, 5, 24, 18, 0, tzinfo=KST)
    assert s.has_success_today(query_kst) is True


def test_has_success_today_false_when_today_only_failed() -> None:
    fixed_kst = datetime(2026, 5, 24, 9, 15, tzinfo=KST)
    s = InMemoryRunStore(now_fn=_fixed_now_fn(fixed_kst))
    r = s.start_run()
    s.mark_finished(r.run_id, status="failed", error="boom")
    query_kst = datetime(2026, 5, 24, 18, 0, tzinfo=KST)
    assert s.has_success_today(query_kst) is False


def test_has_success_today_false_when_yesterday_success() -> None:
    # finished_at = 2026-05-23 23:30 KST (어제)
    fixed_kst = datetime(2026, 5, 23, 23, 30, tzinfo=KST)
    s = InMemoryRunStore(now_fn=_fixed_now_fn(fixed_kst))
    r = s.start_run()
    s.mark_finished(r.run_id, status="success", article_count=5)
    # 오늘 (2026-05-24) 조회
    query_kst = datetime(2026, 5, 24, 9, 0, tzinfo=KST)
    assert s.has_success_today(query_kst) is False


def test_has_success_today_kst_midnight_boundary() -> None:
    # finished_at = 2026-05-24 00:01 KST (오늘 자정 직후)
    fixed_kst = datetime(2026, 5, 24, 0, 1, tzinfo=KST)
    s = InMemoryRunStore(now_fn=_fixed_now_fn(fixed_kst))
    r = s.start_run()
    s.mark_finished(r.run_id, status="success", article_count=5)
    query_kst = datetime(2026, 5, 24, 9, 0, tzinfo=KST)
    assert s.has_success_today(query_kst) is True
    # 다음 날 조회 시 False
    next_day_kst = datetime(2026, 5, 25, 9, 0, tzinfo=KST)
    assert s.has_success_today(next_day_kst) is False


def test_supabase_has_success_today_true() -> None:
    rows = [{"run_id": "r1"}]
    fake = FakeClient(response_queue=[rows])
    s = SupabaseRunStore(fake)
    now_kst = datetime(2026, 5, 24, 10, 0, tzinfo=KST)
    assert s.has_success_today(now_kst) is True
    q = fake.queries[0]
    assert q.eq_col == "status" and q.eq_val == "success"
    assert q.gte_col == "finished_at"
    assert q.lt_col == "finished_at"
    assert q.limited == 1


def test_supabase_has_success_today_false() -> None:
    fake = FakeClient(response_queue=[[]])
    s = SupabaseRunStore(fake)
    now_kst = datetime(2026, 5, 24, 10, 0, tzinfo=KST)
    assert s.has_success_today(now_kst) is False
