from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ai_news_scraping.search_config_store import (
    InMemoryKeywordStore,
    InMemorySettingsStore,
    InMemorySourceStore,
    KeywordRecord,
    SearchSettings,
    SourceRecord,
    SupabaseKeywordStore,
    SupabaseSettingsStore,
    SupabaseSourceStore,
)

# ═══════════════════ InMemory: Keyword ═══════════════════


def test_in_memory_keyword_empty() -> None:
    s = InMemoryKeywordStore()
    assert s.list_all() == []
    assert s.list_active() == []


def test_in_memory_keyword_add_and_list() -> None:
    s = InMemoryKeywordStore()
    r = s.add("artificial intelligence")
    assert r == KeywordRecord(id=1, keyword="artificial intelligence", active=True)
    assert s.list_active() == ["artificial intelligence"]


def test_in_memory_keyword_dedup_and_reactivate() -> None:
    s = InMemoryKeywordStore()
    r1 = s.add("AI")
    s.set_active(r1.id, False)
    r2 = s.add("AI")
    assert r2.id == r1.id
    assert r2.active is True


def test_in_memory_keyword_invalid() -> None:
    s = InMemoryKeywordStore()
    with pytest.raises(ValueError):
        s.add("")
    with pytest.raises(ValueError):
        s.add("   ")


def test_in_memory_keyword_remove() -> None:
    s = InMemoryKeywordStore()
    r = s.add("AI")
    assert s.remove(r.id) is True
    assert s.list_all() == []
    assert s.remove(999) is False


def test_in_memory_keyword_set_active() -> None:
    s = InMemoryKeywordStore()
    r = s.add("AI")
    assert s.set_active(r.id, False) is True
    assert s.list_active() == []
    assert s.list_all()[0].active is False
    assert s.set_active(999, True) is False


def test_in_memory_keyword_bulk_seed() -> None:
    s = InMemoryKeywordStore()
    added = s.bulk_seed(["AI", "LLM", "", "  ", "GenAI"])
    assert added == 3
    assert s.list_active() == ["AI", "LLM", "GenAI"]


# ═══════════════════ InMemory: Source ═══════════════════


def test_in_memory_source_add() -> None:
    s = InMemorySourceStore()
    r = s.add("TechCrunch.com", "TechCrunch")
    assert r == SourceRecord(id=1, domain="techcrunch.com", name="TechCrunch", active=True)


def test_in_memory_source_strips_www() -> None:
    s = InMemorySourceStore()
    r = s.add("www.theverge.com", "The Verge")
    assert r.domain == "theverge.com"


def test_in_memory_source_dedup_updates_name() -> None:
    s = InMemorySourceStore()
    r1 = s.add("a.com", "Old Name")
    r2 = s.add("a.com", "New Name")
    assert r1.id == r2.id
    assert r2.name == "New Name"


def test_in_memory_source_invalid() -> None:
    s = InMemorySourceStore()
    with pytest.raises(ValueError, match="domain"):
        s.add("", "Name")
    with pytest.raises(ValueError, match="name"):
        s.add("a.com", "")


@pytest.mark.parametrize(
    "bad_domain",
    [
        "https://openai.com",  # scheme
        "openai.com:443",  # port
        "openai.com?q=1",  # query
        "open ai.com",  # space
        "openai",  # no dot
        "openai.com/",  # trailing slash
    ],
)
def test_in_memory_source_rejects_non_host_input(bad_domain: str) -> None:
    """Brave site: 가 받지 못하는 형태 (scheme/port/query/공백/no-dot/trailing-slash)
    는 입력 단에서 reject. path 는 허용 (별 테스트)."""
    s = InMemorySourceStore()
    with pytest.raises(ValueError):
        s.add(bad_domain, "X")


def test_normalize_domain_allows_host_with_path() -> None:
    from ai_news_scraping.search_config_store import _normalize_domain
    assert _normalize_domain("openai.com/research") == "openai.com/research"
    assert _normalize_domain("openai.com/research/papers") == "openai.com/research/papers"
    assert _normalize_domain("www.OpenAI.com/News") == "openai.com/news"


def test_normalize_domain_still_rejects_non_path_garbage() -> None:
    from ai_news_scraping.search_config_store import _normalize_domain
    for bad in ["https://openai.com", "openai.com:443", "openai.com?q=1",
                "open ai.com", "openai", "openai.com/"]:
        with pytest.raises(ValueError):
            _normalize_domain(bad)


def test_split_host_path_separates() -> None:
    from ai_news_scraping.search_config_store import _split_host_path
    assert _split_host_path("openai.com") == ("openai.com", "")
    assert _split_host_path("openai.com/research") == ("openai.com", "/research")
    assert _split_host_path("openai.com/research/papers/2026") == (
        "openai.com", "/research/papers/2026"
    )


def test_in_memory_source_update_allows_path() -> None:
    """T1 이후 path 는 허용 (기존 reject 정책 해제)."""
    s = InMemorySourceStore()
    r = s.add("a.com", "A")
    updated = s.update(r.id, domain="a.com/news")
    assert updated is not None
    assert updated.domain == "a.com/news"


def test_in_memory_source_bulk_seed() -> None:
    s = InMemorySourceStore()
    n = s.bulk_seed([("a.com", "A"), ("b.com", "B"), ("", "C")])
    assert n == 2


def test_in_memory_source_bulk_seed_skips_bad_hosts() -> None:
    """seed (yaml 자동 import) 에 잘못된 host 가 섞여 있으면 그 항목만 skip — 전체 실패 X.
    path 는 valid 라 skip 되지 않음. scheme/공백 같은 진짜 잘못된 형태만 skip."""
    s = InMemorySourceStore()
    n = s.bulk_seed([
        ("a.com", "A"),
        ("https://openai.com", "Bad"),  # scheme → skipped
        ("b.com", "B"),
    ])
    assert n == 2
    assert {r.domain for r in s.list_all()} == {"a.com", "b.com"}


def test_in_memory_source_update_all_fields() -> None:
    s = InMemorySourceStore()
    r = s.add("a.com", "A")
    updated = s.update(r.id, domain="b.com", name="B", description="AI 매체")
    assert updated is not None
    assert updated.domain == "b.com"
    assert updated.name == "B"
    assert updated.description == "AI 매체"


def test_in_memory_source_update_partial() -> None:
    s = InMemorySourceStore()
    r = s.add("a.com", "A")
    updated = s.update(r.id, description="설명만")
    assert updated is not None
    assert updated.domain == "a.com"
    assert updated.name == "A"
    assert updated.description == "설명만"


def test_in_memory_source_update_unknown_returns_none() -> None:
    s = InMemorySourceStore()
    assert s.update(999, name="X") is None


def test_in_memory_source_update_empty_domain_raises() -> None:
    s = InMemorySourceStore()
    r = s.add("a.com", "A")
    with pytest.raises(ValueError, match="domain"):
        s.update(r.id, domain="   ")


# ═══════════════════ InMemory: Settings ═══════════════════


def test_in_memory_settings_default() -> None:
    s = InMemorySettingsStore()
    cur = s.get()
    assert cur == SearchSettings()
    assert cur.freshness == "pw"
    assert cur.num_results_per_keyword == 20


def test_in_memory_settings_partial_update() -> None:
    s = InMemorySettingsStore()
    cur = s.update(freshness="pm")
    assert cur.freshness == "pm"
    assert cur.num_results_per_keyword == 20  # 다른 필드는 유지


def test_in_memory_settings_invalid_freshness() -> None:
    s = InMemorySettingsStore()
    with pytest.raises(ValueError, match="freshness"):
        s.update(freshness="px")


def test_in_memory_settings_invalid_ranges() -> None:
    s = InMemorySettingsStore()
    with pytest.raises(ValueError, match="num_results"):
        s.update(num_results_per_keyword=0)
    with pytest.raises(ValueError, match="num_results"):
        s.update(num_results_per_keyword=21)
    with pytest.raises(ValueError, match="max_articles"):
        s.update(max_articles_for_summary=101)
    with pytest.raises(ValueError, match="min_body"):
        s.update(min_body_len=10)


# ═══════════════════ Supabase: fluent mock ═══════════════════


@dataclass
class FakeResp:
    data: Any = None


@dataclass
class FakeQuery:
    selected: tuple[str, ...] = ()
    eq_col: str | None = None
    eq_val: Any = None
    ordered: str | None = None
    single_called: bool = False
    upserted: Any = None
    upsert_on_conflict: str | None = None
    updated: dict[str, Any] | None = None
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

    def single(self) -> FakeQuery:
        self.single_called = True
        return self

    def upsert(self, payload: Any, *, on_conflict: str | None = None) -> FakeQuery:
        self.upserted = payload
        self.upsert_on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.updated = payload
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


# ─── SupabaseKeywordStore ───


def test_supabase_keyword_list_active() -> None:
    fake = FakeClient(response_queue=[[{"keyword": "AI"}, {"keyword": "LLM"}]])
    s = SupabaseKeywordStore(fake)
    assert s.list_active() == ["AI", "LLM"]
    assert fake.schema_name == "ai_news"
    assert fake.table_name == "search_keywords"
    assert fake.queries[0].eq_col == "active"


def test_supabase_keyword_list_all() -> None:
    fake = FakeClient(response_queue=[
        [{"id": 1, "keyword": "AI", "active": True},
         {"id": 2, "keyword": "LLM", "active": False}]
    ])
    s = SupabaseKeywordStore(fake)
    recs = s.list_all()
    assert recs[1] == KeywordRecord(id=2, keyword="LLM", active=False)


def test_supabase_keyword_add() -> None:
    fake = FakeClient(response_queue=[
        [{"id": 7, "keyword": "AI", "active": True}]
    ])
    s = SupabaseKeywordStore(fake)
    r = s.add("AI")
    assert r == KeywordRecord(id=7, keyword="AI", active=True)
    assert fake.queries[0].upserted == {"keyword": "AI", "active": True}
    assert fake.queries[0].upsert_on_conflict == "keyword"


def test_supabase_keyword_remove() -> None:
    fake = FakeClient(response_queue=[[{"id": 3}]])
    s = SupabaseKeywordStore(fake)
    assert s.remove(3) is True
    assert fake.queries[0].deleted is True


def test_supabase_keyword_set_active() -> None:
    fake = FakeClient(response_queue=[[{"id": 3}]])
    s = SupabaseKeywordStore(fake)
    assert s.set_active(3, False) is True
    assert fake.queries[0].updated == {"active": False}


def test_supabase_keyword_bulk_seed() -> None:
    fake = FakeClient(response_queue=[[{"id": 1}, {"id": 2}]])
    s = SupabaseKeywordStore(fake)
    n = s.bulk_seed(["AI", "LLM"])
    assert n == 2
    payload = fake.queries[0].upserted
    assert isinstance(payload, list)
    assert payload[0]["keyword"] == "AI"


# ─── SupabaseSourceStore ───


def test_supabase_source_list_all() -> None:
    fake = FakeClient(response_queue=[
        [{"id": 1, "domain": "a.com", "name": "A", "active": True}]
    ])
    s = SupabaseSourceStore(fake)
    recs = s.list_all()
    assert recs[0] == SourceRecord(id=1, domain="a.com", name="A", active=True)


def test_supabase_source_add() -> None:
    fake = FakeClient(response_queue=[
        [{"id": 5, "domain": "techcrunch.com", "name": "TechCrunch", "active": True}]
    ])
    s = SupabaseSourceStore(fake)
    r = s.add("www.TechCrunch.com", " TechCrunch ")
    assert r.domain == "techcrunch.com"
    assert fake.queries[0].upsert_on_conflict == "domain"


# ─── SupabaseSettingsStore ───


def test_supabase_settings_get() -> None:
    fake = FakeClient(response_queue=[
        {"freshness": "pm", "num_results_per_keyword": 15,
         "max_articles_for_summary": 30, "min_body_len": 400}
    ])
    s = SupabaseSettingsStore(fake)
    cur = s.get()
    assert cur == SearchSettings(
        freshness="pm",
        num_results_per_keyword=15,
        max_articles_for_summary=30,
        min_body_len=400,
    )


def test_supabase_settings_update_with_validation() -> None:
    fake = FakeClient(response_queue=[
        None,  # update execute
        {"freshness": "pd", "num_results_per_keyword": 20,
         "max_articles_for_summary": 20, "min_body_len": 300},
    ])
    s = SupabaseSettingsStore(fake)
    cur = s.update(freshness="pd")
    assert cur.freshness == "pd"
    upd = fake.queries[0].updated
    assert upd is not None
    assert upd["freshness"] == "pd"
    assert "updated_at" in upd


def test_supabase_settings_update_invalid_short_circuits() -> None:
    fake = FakeClient()
    s = SupabaseSettingsStore(fake)
    with pytest.raises(ValueError):
        s.update(freshness="px")
    # 검증 실패 → DB 호출 0
    assert fake.queries == []


def test_supabase_settings_update_empty_payload_returns_current() -> None:
    fake = FakeClient(response_queue=[
        {"freshness": "pw", "num_results_per_keyword": 20,
         "max_articles_for_summary": 20, "min_body_len": 300}
    ])
    s = SupabaseSettingsStore(fake)
    cur = s.update()
    assert cur == SearchSettings()
    # update 없이 바로 get 만 호출
    assert all(q.updated is None for q in fake.queries)
