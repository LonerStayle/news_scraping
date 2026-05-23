"""검색 조건 admin 화 — 키워드 / 매체 / 운영 옵션 store.

3 protocol (KeywordStore / SourceStore / SettingsStore) + 각각 InMemory + Supabase.
yaml (domains/<name>/*.yaml) 은 seed 용 — pipeline 은 DB 우선, DB 비었으면
yaml fallback (Phase F3/F4 에서 처리).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class KeywordRecord:
    id: int
    keyword: str
    active: bool


@dataclass(frozen=True)
class SourceRecord:
    id: int
    domain: str
    name: str
    active: bool
    description: str | None = None


@dataclass(frozen=True)
class SearchSettings:
    freshness: str = "pw"
    num_results_per_keyword: int = 20
    max_articles_for_summary: int = 20
    min_body_len: int = 300


# ════════════════════════════ KeywordStore ════════════════════════════


class KeywordStore(Protocol):
    def list_active(self) -> list[str]: ...
    def list_all(self) -> list[KeywordRecord]: ...
    def add(self, keyword: str) -> KeywordRecord: ...
    def remove(self, record_id: int) -> bool: ...
    def set_active(self, record_id: int, active: bool) -> bool: ...
    def bulk_seed(self, keywords: list[str]) -> int: ...


class InMemoryKeywordStore:
    def __init__(self) -> None:
        self._next_id = 1
        self._items: dict[int, KeywordRecord] = {}

    def list_active(self) -> list[str]:
        return [r.keyword for r in self._sorted() if r.active]

    def list_all(self) -> list[KeywordRecord]:
        return self._sorted()

    def add(self, keyword: str) -> KeywordRecord:
        kw = keyword.strip()
        if not kw:
            raise ValueError(f"keyword must be non-empty: {keyword!r}")
        for r in self._items.values():
            if r.keyword == kw:
                if not r.active:
                    self._items[r.id] = replace(r, active=True)
                return self._items[r.id]
        rec = KeywordRecord(id=self._next_id, keyword=kw, active=True)
        self._items[self._next_id] = rec
        self._next_id += 1
        return rec

    def remove(self, record_id: int) -> bool:
        return self._items.pop(record_id, None) is not None

    def set_active(self, record_id: int, active: bool) -> bool:
        if record_id not in self._items:
            return False
        self._items[record_id] = replace(self._items[record_id], active=active)
        return True

    def bulk_seed(self, keywords: list[str]) -> int:
        before = len(self._items)
        for kw in keywords:
            if kw.strip():
                self.add(kw)
        return len(self._items) - before

    def _sorted(self) -> list[KeywordRecord]:
        return sorted(self._items.values(), key=lambda r: r.id)


class SupabaseKeywordStore:
    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self) -> Any:
        return self._client.schema(self._schema).table("search_keywords")

    def list_active(self) -> list[str]:
        resp = (
            self._table()
            .select("keyword")
            .eq("active", True)
            .order("id")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return [str(r["keyword"]) for r in rows if "keyword" in r]

    def list_all(self) -> list[KeywordRecord]:
        resp = self._table().select("id, keyword, active").order("id").execute()
        rows = getattr(resp, "data", None) or []
        return [
            KeywordRecord(
                id=int(r["id"]),
                keyword=str(r["keyword"]),
                active=bool(r.get("active", True)),
            )
            for r in rows
        ]

    def add(self, keyword: str) -> KeywordRecord:
        kw = keyword.strip()
        if not kw:
            raise ValueError(f"keyword must be non-empty: {keyword!r}")
        resp = (
            self._table()
            .upsert({"keyword": kw, "active": True}, on_conflict="keyword")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            raise RuntimeError("upsert returned no rows")
        row = rows[0]
        return KeywordRecord(
            id=int(row["id"]),
            keyword=str(row["keyword"]),
            active=bool(row.get("active", True)),
        )

    def remove(self, record_id: int) -> bool:
        resp = self._table().delete().eq("id", record_id).execute()
        rows = getattr(resp, "data", None) or []
        return len(rows) > 0

    def set_active(self, record_id: int, active: bool) -> bool:
        resp = (
            self._table().update({"active": active}).eq("id", record_id).execute()
        )
        rows = getattr(resp, "data", None) or []
        return len(rows) > 0

    def bulk_seed(self, keywords: list[str]) -> int:
        payload = [
            {"keyword": kw.strip(), "active": True}
            for kw in keywords
            if kw.strip()
        ]
        if not payload:
            return 0
        resp = self._table().upsert(payload, on_conflict="keyword").execute()
        rows = getattr(resp, "data", None) or []
        return len(rows)


# ════════════════════════════ SourceStore ════════════════════════════


class SourceStore(Protocol):
    def list_active(self) -> list[SourceRecord]: ...
    def list_all(self) -> list[SourceRecord]: ...
    def add(self, domain: str, name: str) -> SourceRecord: ...
    def remove(self, record_id: int) -> bool: ...
    def set_active(self, record_id: int, active: bool) -> bool: ...
    def update(
        self,
        record_id: int,
        *,
        domain: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SourceRecord | None: ...
    def bulk_seed(self, sources: list[tuple[str, str]]) -> int: ...


class InMemorySourceStore:
    def __init__(self) -> None:
        self._next_id = 1
        self._items: dict[int, SourceRecord] = {}

    def list_active(self) -> list[SourceRecord]:
        return [r for r in self._sorted() if r.active]

    def list_all(self) -> list[SourceRecord]:
        return self._sorted()

    def add(self, domain: str, name: str) -> SourceRecord:
        d = domain.strip().lower().removeprefix("www.")
        n = name.strip()
        if not d:
            raise ValueError(f"domain must be non-empty: {domain!r}")
        if not n:
            raise ValueError(f"name must be non-empty: {name!r}")
        for r in self._items.values():
            if r.domain == d:
                self._items[r.id] = replace(r, name=n, active=True)
                return self._items[r.id]
        rec = SourceRecord(id=self._next_id, domain=d, name=n, active=True)
        self._items[self._next_id] = rec
        self._next_id += 1
        return rec

    def remove(self, record_id: int) -> bool:
        return self._items.pop(record_id, None) is not None

    def set_active(self, record_id: int, active: bool) -> bool:
        if record_id not in self._items:
            return False
        self._items[record_id] = replace(self._items[record_id], active=active)
        return True

    def update(
        self,
        record_id: int,
        *,
        domain: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SourceRecord | None:
        if record_id not in self._items:
            return None
        cur = self._items[record_id]
        new_domain = cur.domain
        new_name = cur.name
        if domain is not None:
            new_domain = domain.strip().lower().removeprefix("www.")
            if not new_domain:
                raise ValueError(f"domain must be non-empty: {domain!r}")
        if name is not None:
            new_name = name.strip()
            if not new_name:
                raise ValueError(f"name must be non-empty: {name!r}")
        new_desc = description if description is not None else cur.description
        if new_desc is not None:
            new_desc = new_desc.strip() or None
        updated = replace(
            cur, domain=new_domain, name=new_name, description=new_desc
        )
        self._items[record_id] = updated
        return updated

    def bulk_seed(self, sources: list[tuple[str, str]]) -> int:
        before = len(self._items)
        for domain, name in sources:
            if domain.strip() and name.strip():
                self.add(domain, name)
        return len(self._items) - before

    def _sorted(self) -> list[SourceRecord]:
        return sorted(self._items.values(), key=lambda r: r.id)


class SupabaseSourceStore:
    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self) -> Any:
        return self._client.schema(self._schema).table("search_sources")

    def list_active(self) -> list[SourceRecord]:
        return [r for r in self.list_all() if r.active]

    def list_all(self) -> list[SourceRecord]:
        resp = (
            self._table()
            .select("id, domain, name, active, description")
            .order("id")
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return [
            SourceRecord(
                id=int(r["id"]),
                domain=str(r["domain"]),
                name=str(r["name"]),
                active=bool(r.get("active", True)),
                description=r.get("description"),
            )
            for r in rows
        ]

    def add(self, domain: str, name: str) -> SourceRecord:
        d = domain.strip().lower().removeprefix("www.")
        n = name.strip()
        if not d:
            raise ValueError(f"domain must be non-empty: {domain!r}")
        if not n:
            raise ValueError(f"name must be non-empty: {name!r}")
        resp = (
            self._table()
            .upsert(
                {"domain": d, "name": n, "active": True}, on_conflict="domain"
            )
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            raise RuntimeError("upsert returned no rows")
        row = rows[0]
        return SourceRecord(
            id=int(row["id"]),
            domain=str(row["domain"]),
            name=str(row["name"]),
            active=bool(row.get("active", True)),
        )

    def remove(self, record_id: int) -> bool:
        resp = self._table().delete().eq("id", record_id).execute()
        rows = getattr(resp, "data", None) or []
        return len(rows) > 0

    def set_active(self, record_id: int, active: bool) -> bool:
        resp = (
            self._table().update({"active": active}).eq("id", record_id).execute()
        )
        rows = getattr(resp, "data", None) or []
        return len(rows) > 0

    def update(
        self,
        record_id: int,
        *,
        domain: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> SourceRecord | None:
        payload: dict[str, Any] = {}
        if domain is not None:
            cleaned = domain.strip().lower().removeprefix("www.")
            if not cleaned:
                raise ValueError(f"domain must be non-empty: {domain!r}")
            payload["domain"] = cleaned
        if name is not None:
            cleaned_name = name.strip()
            if not cleaned_name:
                raise ValueError(f"name must be non-empty: {name!r}")
            payload["name"] = cleaned_name
        if description is not None:
            payload["description"] = description.strip() or None
        if not payload:
            return None
        resp = self._table().update(payload).eq("id", record_id).execute()
        rows = getattr(resp, "data", None) or []
        if not rows:
            return None
        row = rows[0]
        return SourceRecord(
            id=int(row["id"]),
            domain=str(row["domain"]),
            name=str(row["name"]),
            active=bool(row.get("active", True)),
            description=row.get("description"),
        )

    def bulk_seed(self, sources: list[tuple[str, str]]) -> int:
        payload = [
            {
                "domain": d.strip().lower().removeprefix("www."),
                "name": n.strip(),
                "active": True,
            }
            for d, n in sources
            if d.strip() and n.strip()
        ]
        if not payload:
            return 0
        resp = self._table().upsert(payload, on_conflict="domain").execute()
        rows = getattr(resp, "data", None) or []
        return len(rows)


# ════════════════════════════ SettingsStore ════════════════════════════


_ALLOWED_FRESHNESS = {"pd", "pw", "pm", "py"}


def _validate_settings_update(
    freshness: str | None,
    num_results_per_keyword: int | None,
    max_articles_for_summary: int | None,
    min_body_len: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if freshness is not None:
        if freshness not in _ALLOWED_FRESHNESS:
            raise ValueError(f"freshness must be one of {_ALLOWED_FRESHNESS}: {freshness!r}")
        payload["freshness"] = freshness
    if num_results_per_keyword is not None:
        if not 1 <= num_results_per_keyword <= 20:
            raise ValueError(f"num_results_per_keyword must be 1..20: {num_results_per_keyword}")
        payload["num_results_per_keyword"] = num_results_per_keyword
    if max_articles_for_summary is not None:
        if not 1 <= max_articles_for_summary <= 100:
            raise ValueError(f"max_articles_for_summary must be 1..100: {max_articles_for_summary}")
        payload["max_articles_for_summary"] = max_articles_for_summary
    if min_body_len is not None:
        if not 50 <= min_body_len <= 5000:
            raise ValueError(f"min_body_len must be 50..5000: {min_body_len}")
        payload["min_body_len"] = min_body_len
    return payload


class SettingsStore(Protocol):
    def get(self) -> SearchSettings: ...
    def update(
        self,
        *,
        freshness: str | None = None,
        num_results_per_keyword: int | None = None,
        max_articles_for_summary: int | None = None,
        min_body_len: int | None = None,
    ) -> SearchSettings: ...


class InMemorySettingsStore:
    def __init__(self, initial: SearchSettings | None = None) -> None:
        self._current = initial if initial is not None else SearchSettings()

    def get(self) -> SearchSettings:
        return self._current

    def update(
        self,
        *,
        freshness: str | None = None,
        num_results_per_keyword: int | None = None,
        max_articles_for_summary: int | None = None,
        min_body_len: int | None = None,
    ) -> SearchSettings:
        payload = _validate_settings_update(
            freshness, num_results_per_keyword, max_articles_for_summary, min_body_len
        )
        self._current = replace(self._current, **payload)
        return self._current


class SupabaseSettingsStore:
    SINGLETON_ID = 1

    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self) -> Any:
        return self._client.schema(self._schema).table("search_settings")

    def get(self) -> SearchSettings:
        resp = (
            self._table()
            .select(
                "freshness, num_results_per_keyword, "
                "max_articles_for_summary, min_body_len"
            )
            .eq("id", self.SINGLETON_ID)
            .single()
            .execute()
        )
        row = getattr(resp, "data", None) or {}
        return SearchSettings(
            freshness=str(row.get("freshness", "pw")),
            num_results_per_keyword=int(row.get("num_results_per_keyword", 20)),
            max_articles_for_summary=int(row.get("max_articles_for_summary", 20)),
            min_body_len=int(row.get("min_body_len", 300)),
        )

    def update(
        self,
        *,
        freshness: str | None = None,
        num_results_per_keyword: int | None = None,
        max_articles_for_summary: int | None = None,
        min_body_len: int | None = None,
    ) -> SearchSettings:
        payload = _validate_settings_update(
            freshness, num_results_per_keyword, max_articles_for_summary, min_body_len
        )
        if not payload:
            return self.get()
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._table().update(payload).eq("id", self.SINGLETON_ID).execute()
        return self.get()
