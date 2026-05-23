from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_news_scraping.extract import ExtractedArticle
from ai_news_scraping.store import (
    InMemoryArticleStore,
    StoredArticle,
    SupabaseArticleStore,
)


def _make_article(url: str = "https://x.com/a", **overrides: Any) -> ExtractedArticle:
    defaults: dict[str, Any] = {
        "url": url,
        "title": "T",
        "body_text": "B" * 300,
        "raw_html_excerpt": "<html>",
        "published_at": "2026-05-23",
        "source_domain": "x.com",
    }
    defaults.update(overrides)
    return ExtractedArticle(**defaults)


# ────────── InMemoryArticleStore ──────────


def test_in_memory_starts_empty() -> None:
    store = InMemoryArticleStore()
    assert store.existing_urls(["https://x.com/a"]) == set()
    assert store.articles == {}


def test_in_memory_upsert_then_existing() -> None:
    store = InMemoryArticleStore()
    store.upsert_article(_make_article(), keyword="kw1", run_id="r1")
    assert store.existing_urls(["https://x.com/a", "https://x.com/b"]) == {
        "https://x.com/a"
    }
    stored = store.articles["https://x.com/a"]
    assert isinstance(stored, StoredArticle)
    assert stored.keyword == "kw1"
    assert stored.run_id == "r1"
    assert stored.source_domain == "x.com"
    assert stored.published_at == "2026-05-23"


def test_in_memory_upsert_overwrites_latest_run() -> None:
    store = InMemoryArticleStore()
    store.upsert_article(_make_article(), keyword="k1", run_id="r1")
    store.upsert_article(_make_article(), keyword="k2", run_id="r2")
    assert len(store.articles) == 1
    assert store.articles["https://x.com/a"].keyword == "k2"
    assert store.articles["https://x.com/a"].run_id == "r2"


# ────────── SupabaseArticleStore — fluent mock ──────────


@dataclass
class FakeResponse:
    data: list[dict[str, Any]] | None = None


@dataclass
class FakeQuery:
    """Records the call chain and returns the configured response."""

    selected_cols: tuple[str, ...] = ()
    filter_col: str | None = None
    filter_values: list[str] | None = None
    upserted: dict[str, Any] | None = None
    upsert_on_conflict: str | None = None
    response: FakeResponse = field(default_factory=FakeResponse)

    def select(self, *cols: str) -> FakeQuery:
        self.selected_cols = cols
        return self

    def in_(self, col: str, values: list[str]) -> FakeQuery:
        self.filter_col = col
        self.filter_values = values
        return self

    def upsert(
        self, payload: dict[str, Any], *, on_conflict: str | None = None
    ) -> FakeQuery:
        self.upserted = payload
        self.upsert_on_conflict = on_conflict
        return self

    def execute(self) -> FakeResponse:
        return self.response


@dataclass
class FakeSupabaseClient:
    table_name: str | None = None
    query: FakeQuery = field(default_factory=FakeQuery)

    def table(self, name: str) -> FakeQuery:
        self.table_name = name
        return self.query


def test_supabase_existing_urls_empty_input_skips_call() -> None:
    fake = FakeSupabaseClient()
    store = SupabaseArticleStore(fake)
    assert store.existing_urls([]) == set()
    assert fake.table_name is None


def test_supabase_existing_urls_queries_articles_table() -> None:
    fake = FakeSupabaseClient(
        query=FakeQuery(response=FakeResponse(data=[{"url": "https://x.com/a"}]))
    )
    store = SupabaseArticleStore(fake)
    result = store.existing_urls(["https://x.com/a", "https://x.com/b"])
    assert result == {"https://x.com/a"}
    assert fake.table_name == "articles"
    assert fake.query.selected_cols == ("url",)
    assert fake.query.filter_col == "url"
    assert fake.query.filter_values == ["https://x.com/a", "https://x.com/b"]


def test_supabase_existing_urls_handles_none_data() -> None:
    fake = FakeSupabaseClient(query=FakeQuery(response=FakeResponse(data=None)))
    store = SupabaseArticleStore(fake)
    assert store.existing_urls(["https://x.com/a"]) == set()


def test_supabase_upsert_article_sends_full_payload() -> None:
    fake = FakeSupabaseClient()
    store = SupabaseArticleStore(fake)
    store.upsert_article(_make_article(), keyword="kw1", run_id="r1")
    assert fake.table_name == "articles"
    assert fake.query.upsert_on_conflict == "url"
    payload = fake.query.upserted
    assert payload is not None
    assert payload["url"] == "https://x.com/a"
    assert payload["keyword"] == "kw1"
    assert payload["run_id"] == "r1"
    assert payload["source_domain"] == "x.com"
    assert payload["published_at"] == "2026-05-23"
    assert "body_text" in payload
    assert "raw_html_excerpt" in payload
