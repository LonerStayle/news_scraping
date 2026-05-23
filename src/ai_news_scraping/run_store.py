"""Run history store — runs 테이블 (CLAUDE.md §3, 0001 schema).

발송 이력을 다 남긴다 (대표님 Phase G 요구). start_run 시 uuid + status=
"running" 으로 insert, pipeline 종료 시 mark_finished 로 status/article_count/
error/digest 갱신. admin History 탭이 list_recent() 로 표시.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

VALID_STATUSES = {"running", "success", "failed", "skipped"}


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    article_count: int = 0
    status: str = "running"
    error: str | None = None
    digest_text: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class RunStore(Protocol):
    def start_run(self) -> RunRecord: ...
    def mark_finished(
        self,
        run_id: str,
        *,
        status: str,
        article_count: int = 0,
        error: str | None = None,
        digest_text: str | None = None,
    ) -> None: ...
    def list_recent(self, limit: int = 20) -> list[RunRecord]: ...
    def get_last_success(self) -> RunRecord | None: ...


class InMemoryRunStore:
    def __init__(self, now_fn: Any = None) -> None:
        self._items: dict[str, RunRecord] = {}
        self._now_fn = now_fn or _now

    def start_run(self) -> RunRecord:
        rec = RunRecord(
            run_id=str(uuid.uuid4()),
            started_at=self._now_fn(),
            status="running",
        )
        self._items[rec.run_id] = rec
        return rec

    def mark_finished(
        self,
        run_id: str,
        *,
        status: str,
        article_count: int = 0,
        error: str | None = None,
        digest_text: str | None = None,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        if run_id not in self._items:
            raise KeyError(f"run not found: {run_id}")
        cur = self._items[run_id]
        self._items[run_id] = replace(
            cur,
            finished_at=self._now_fn(),
            status=status,
            article_count=article_count,
            error=error,
            digest_text=digest_text,
        )

    def list_recent(self, limit: int = 20) -> list[RunRecord]:
        return sorted(
            self._items.values(), key=lambda r: r.started_at, reverse=True
        )[:limit]

    def get_last_success(self) -> RunRecord | None:
        for r in self.list_recent(limit=10_000):
            if r.status == "success":
                return r
        return None


class SupabaseRunStore:
    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self) -> Any:
        return self._client.schema(self._schema).table("runs")

    def start_run(self) -> RunRecord:
        run_id = str(uuid.uuid4())
        started_at = _now()
        payload = {
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "status": "running",
            "article_count": 0,
        }
        self._table().insert(payload).execute()
        return RunRecord(
            run_id=run_id, started_at=started_at, status="running"
        )

    def mark_finished(
        self,
        run_id: str,
        *,
        status: str,
        article_count: int = 0,
        error: str | None = None,
        digest_text: str | None = None,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        payload: dict[str, Any] = {
            "finished_at": _now().isoformat(),
            "status": status,
            "article_count": article_count,
        }
        if error is not None:
            payload["error"] = error
        if digest_text is not None:
            payload["digest_text"] = digest_text
        self._table().update(payload).eq("run_id", run_id).execute()

    def list_recent(self, limit: int = 20) -> list[RunRecord]:
        resp = (
            self._table()
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return [_row_to_record(r) for r in rows]

    def get_last_success(self) -> RunRecord | None:
        resp = (
            self._table()
            .select("*")
            .eq("status", "success")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            return None
        return _row_to_record(rows[0])


def _row_to_record(r: dict[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=str(r["run_id"]),
        started_at=_parse_dt(r.get("started_at")),
        finished_at=_parse_dt_opt(r.get("finished_at")),
        article_count=int(r.get("article_count", 0)),
        status=str(r.get("status", "running")),
        error=r.get("error"),
        digest_text=r.get("digest_text"),
    )


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return _now()


def _parse_dt_opt(v: Any) -> datetime | None:
    if v is None:
        return None
    return _parse_dt(v)


# Silence unused-field warning on imports
_ = field
