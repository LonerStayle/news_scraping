"""Subscriber list store — Supabase + InMemory.

Admin 페이지의 구독자 추가/제거, 그리고 메일 발송 시 active 명단 조회의
공용 인터페이스.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Subscriber:
    id: int
    email: str
    active: bool


class SubscriberStore(Protocol):
    def list_active_emails(self) -> list[str]: ...
    def list_all(self) -> list[Subscriber]: ...
    def add(self, email: str) -> Subscriber: ...
    def remove(self, subscriber_id: int) -> bool: ...


def _validate_email(email: str) -> str:
    cleaned = email.strip()
    if "@" not in cleaned:
        raise ValueError(f"invalid email: {email!r}")
    local, _, domain = cleaned.rpartition("@")
    if not local or not domain or "." not in domain:
        raise ValueError(f"invalid email: {email!r}")
    return cleaned


class InMemorySubscriberStore:
    def __init__(self) -> None:
        self._next_id = 1
        self._items: dict[int, Subscriber] = {}

    def list_active_emails(self) -> list[str]:
        return [s.email for s in self._items.values() if s.active]

    def list_all(self) -> list[Subscriber]:
        return sorted(self._items.values(), key=lambda s: s.id)

    def add(self, email: str) -> Subscriber:
        cleaned = _validate_email(email)
        for s in list(self._items.values()):
            if s.email == cleaned:
                if not s.active:
                    reactivated = Subscriber(id=s.id, email=s.email, active=True)
                    self._items[s.id] = reactivated
                    return reactivated
                return s
        sub = Subscriber(id=self._next_id, email=cleaned, active=True)
        self._items[self._next_id] = sub
        self._next_id += 1
        return sub

    def remove(self, subscriber_id: int) -> bool:
        return self._items.pop(subscriber_id, None) is not None


class SupabaseSubscriberStore:
    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self, name: str) -> Any:
        return self._client.schema(self._schema).table(name)

    def list_active_emails(self) -> list[str]:
        resp = (
            self._table("subscribers")
            .select("email")
            .eq("active", True)
            .execute()
        )
        data = getattr(resp, "data", None) or []
        return [str(r["email"]) for r in data if "email" in r]

    def list_all(self) -> list[Subscriber]:
        resp = (
            self._table("subscribers")
            .select("id, email, active")
            .order("id")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return [
            Subscriber(
                id=int(r["id"]),
                email=str(r["email"]),
                active=bool(r.get("active", True)),
            )
            for r in rows
        ]

    def add(self, email: str) -> Subscriber:
        cleaned = _validate_email(email)
        resp = (
            self._table("subscribers")
            .upsert({"email": cleaned, "active": True}, on_conflict="email")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            raise RuntimeError("upsert returned no rows")
        row = rows[0]
        return Subscriber(
            id=int(row["id"]),
            email=str(row["email"]),
            active=bool(row.get("active", True)),
        )

    def remove(self, subscriber_id: int) -> bool:
        resp = (
            self._table("subscribers")
            .delete()
            .eq("id", subscriber_id)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return len(rows) > 0
