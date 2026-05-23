"""Article store — Supabase article 영속화 + URL dedup.

운영 시 ``SupabaseArticleStore`` 가 supabase-py 클라이언트로 articles 테이블에
upsert. 테스트는 ``InMemoryArticleStore`` (동일 protocol) 로 빠르게 검증.
호출측은 보통:

    existing = store.existing_urls(search_urls)
    new_urls = [u for u in search_urls if u not in existing]
    # ... extract.extract(url) per new_url ...
    store.upsert_article(article, keyword=k, run_id=run_id)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from .extract import ExtractedArticle


@dataclass(frozen=True)
class StoredArticle:
    url: str
    title: str
    source_domain: str
    published_at: str | None
    body_text: str
    raw_html_excerpt: str
    keyword: str
    run_id: str


class ArticleStore(Protocol):
    def existing_urls(self, urls: Iterable[str]) -> set[str]: ...
    def upsert_article(
        self, article: ExtractedArticle, *, keyword: str, run_id: str
    ) -> None: ...


class InMemoryArticleStore:
    """In-memory implementation. Test / dry-run only."""

    def __init__(self) -> None:
        self._articles: dict[str, StoredArticle] = {}

    def existing_urls(self, urls: Iterable[str]) -> set[str]:
        return {u for u in urls if u in self._articles}

    def upsert_article(
        self, article: ExtractedArticle, *, keyword: str, run_id: str
    ) -> None:
        self._articles[article.url] = StoredArticle(
            url=article.url,
            title=article.title,
            source_domain=article.source_domain,
            published_at=article.published_at,
            body_text=article.body_text,
            raw_html_excerpt=article.raw_html_excerpt,
            keyword=keyword,
            run_id=run_id,
        )

    @property
    def articles(self) -> dict[str, StoredArticle]:
        return self._articles


class SupabaseArticleStore:
    """Production store backed by supabase-py ``Client``."""

    def __init__(self, client: Any, *, schema: str = "ai_news") -> None:
        self._client = client
        self._schema = schema

    def _table(self, name: str) -> Any:
        return self._client.schema(self._schema).table(name)

    def existing_urls(self, urls: Iterable[str]) -> set[str]:
        url_list = list(urls)
        if not url_list:
            return set()
        resp = (
            self._table("articles")
            .select("url")
            .in_("url", url_list)
            .execute()
        )
        data = getattr(resp, "data", None) or []
        return {str(row["url"]) for row in data if "url" in row}

    def upsert_article(
        self, article: ExtractedArticle, *, keyword: str, run_id: str
    ) -> None:
        payload: dict[str, Any] = {
            "url": article.url,
            "title": article.title,
            "source_domain": article.source_domain,
            "published_at": article.published_at,
            "body_text": article.body_text,
            "raw_html_excerpt": article.raw_html_excerpt,
            "keyword": keyword,
            "run_id": run_id,
        }
        (
            self._table("articles")
            .upsert(payload, on_conflict="url")
            .execute()
        )
