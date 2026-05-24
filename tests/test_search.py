from __future__ import annotations

from typing import Any

import pytest

from ai_news_scraping.search import (
    BRAVE_MAX_COUNT,
    BRAVE_SEARCH_ENDPOINT,
    SearchResult,
    _matches_path_prefix,
    build_query,
    search,
)


def test_matches_path_prefix_segment_aware() -> None:
    # 빈 prefix → 모두 매치 (host-only row, FR-2)
    assert _matches_path_prefix("/research/x", "") is True
    assert _matches_path_prefix("/anything", "") is True
    assert _matches_path_prefix("/x", "/") is True
    # 정확 매치 / 하위 segment 매치
    assert _matches_path_prefix("/research", "/research") is True
    assert _matches_path_prefix("/research/x", "/research") is True
    assert _matches_path_prefix("/research/papers/2026", "/research/papers") is True
    # segment boundary — false positive 차단 (D2 핵심)
    assert _matches_path_prefix("/researchers/x", "/research") is False
    assert _matches_path_prefix("/research-old/x", "/research") is False
    # prefix 끝 슬래시 정규화
    assert _matches_path_prefix("/research/x", "/research/") is True
    # 차단
    assert _matches_path_prefix("/news/x", "/research") is False


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> Any:
        self.calls.append({
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return FakeResponse(self.payload)


# ─────────── build_query ───────────


def test_build_query_combines_keyword_and_sites() -> None:
    q = build_query("AI safety", ["a.com", "b.com"])
    assert q == '"AI safety" (site:a.com OR site:b.com)'


def test_build_query_rejects_empty_keyword() -> None:
    with pytest.raises(ValueError, match="keyword"):
        build_query("   ", ["a.com"])


def test_build_query_rejects_empty_sources() -> None:
    with pytest.raises(ValueError, match="source_domains"):
        build_query("kw", [])


# ─────────── search ───────────


def test_search_returns_whitelisted_results_only() -> None:
    session = FakeSession(
        {
            "web": {
                "results": [
                    {
                        "title": "AI breakthrough",
                        "url": "https://techcrunch.com/2026/05/ai-breakthrough-launch/",
                        "description": "snippet 1",
                        "meta_url": {"hostname": "techcrunch.com"},
                    },
                    {
                        "title": "Off-whitelist leak",
                        "url": "https://random.com/x",
                        "description": "snippet 2",
                        "meta_url": {"hostname": "random.com"},
                    },
                ]
            }
        }
    )
    results = search(
        "AI",
        ["techcrunch.com", "wired.com"],
        api_key="k",
        session=session,
    )
    assert len(results) == 1
    assert results[0] == SearchResult(
        url="https://techcrunch.com/2026/05/ai-breakthrough-launch/",
        title="AI breakthrough",
        snippet="snippet 1",
        source_domain="techcrunch.com",
        keyword="AI",
    )


def test_search_filters_out_category_and_homepage_urls() -> None:
    """Brave 가 매체 카테고리/홈페이지를 freshness=pd 결과에 섞어줘도 제외."""
    session = FakeSession(
        {
            "web": {
                "results": [
                    # 차단되어야 할 URL 들
                    {"title": "Home", "url": "https://a.com/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                    {"title": "Blog", "url": "https://a.com/blog/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                    {"title": "Category", "url": "https://a.com/category/ai/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                    {"title": "Models", "url": "https://a.com/models/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                    {"title": "Short", "url": "https://a.com/products/x/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                    # 통과해야 할 진짜 기사 URL
                    {"title": "Real article",
                     "url": "https://a.com/2026/05/openai-launches-new-model/",
                     "description": "s", "meta_url": {"hostname": "a.com"}},
                ]
            }
        }
    )
    results = search("AI", ["a.com"], api_key="k", session=session)
    assert len(results) == 1
    assert results[0].title == "Real article"


def test_search_strips_www_prefix_from_hostname() -> None:
    session = FakeSession(
        {
            "web": {
                "results": [
                    {
                        "title": "T",
                        "url": "https://www.theverge.com/2026/05/ai-policy-breakdown-news/",
                        "description": "s",
                        "meta_url": {"hostname": "www.theverge.com"},
                    }
                ]
            }
        }
    )
    results = search("AI", ["theverge.com"], api_key="k", session=session)
    assert len(results) == 1
    assert results[0].source_domain == "theverge.com"


def test_search_sends_expected_headers_and_params() -> None:
    session = FakeSession({"web": {"results": []}})
    search("AI", ["a.com"], api_key="K1", session=session)
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == BRAVE_SEARCH_ENDPOINT
    assert call["headers"]["X-Subscription-Token"] == "K1"
    assert call["headers"]["Accept"] == "application/json"
    assert call["params"]["freshness"] == "pd"
    assert call["params"]["count"] == 10
    assert "site:a.com" in call["params"]["q"]


def test_search_empty_response() -> None:
    results = search(
        "AI", ["a.com"], api_key="k", session=FakeSession({})
    )
    assert results == []


def test_search_missing_web_key() -> None:
    results = search(
        "AI", ["a.com"], api_key="k", session=FakeSession({"other": "x"})
    )
    assert results == []


def test_search_count_clamped_to_max() -> None:
    session = FakeSession({"web": {"results": []}})
    search("AI", ["a.com"], api_key="k", num=999, session=session)
    assert session.calls[0]["params"]["count"] == BRAVE_MAX_COUNT


def test_search_filters_by_path_prefix_and_dedups_host() -> None:
    """3 row (host-only X + /research + /news) → Brave 에는 site:openai.com 1번만 /
    결과 필터는 row 별 path_prefix 매칭 + segment-aware."""
    from ai_news_scraping.search_config_loader import SourceEntry

    session = FakeSession({"web": {"results": [
        {"url": "https://openai.com/research/papers/2026/new-reasoning-paper",
         "title": "Paper", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/news/funding-round-details-2026",
         "title": "News", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/researchers/team-page-overview",  # segment false positive 후보
         "title": "Team", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/blog/general-update-spring-2026",  # 어느 prefix 도 안 매치
         "title": "Blog", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
    ]}})

    entries = [
        SourceEntry(host="openai.com", path_prefix="/research", name="OpenAI Research"),
        SourceEntry(host="openai.com", path_prefix="/news", name="OpenAI News"),
    ]
    results = search("AI", entries, api_key="K", session=session)

    # Brave 쿼리에 site:openai.com 이 1번만 들어가야 (host dedup)
    q = session.calls[0]["params"]["q"]
    assert q.count("site:openai.com") == 1

    # 결과: /research/... + /news/... 통과, /researchers/... 차단 (segment), /blog/... 차단
    urls = {r.url for r in results}
    assert "https://openai.com/research/papers/2026/new-reasoning-paper" in urls
    assert "https://openai.com/news/funding-round-details-2026" in urls
    assert "https://openai.com/researchers/team-page-overview" not in urls
    assert "https://openai.com/blog/general-update-spring-2026" not in urls


def test_search_host_only_row_lets_all_segments_through() -> None:
    """host-only row 면 path 무관 모두 통과 (FR-2)."""
    from ai_news_scraping.search_config_loader import SourceEntry

    session = FakeSession({"web": {"results": [
        {"url": "https://openai.com/research/papers/some-new-paper-xyz",
         "title": "T1", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/news/funding-round-news-spring",
         "title": "T2", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/blog/general-update-spring-2026",
         "title": "T3", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
    ]}})
    entries = [SourceEntry(host="openai.com", path_prefix="", name="OpenAI")]
    results = search("AI", entries, api_key="K", session=session)
    assert len(results) == 3


def test_search_host_only_takes_priority_over_path_row() -> None:
    """D5: 같은 host 에 host-only row + path row 가 공존하면 host-only 가 우선 — 모두 통과."""
    from ai_news_scraping.search_config_loader import SourceEntry

    session = FakeSession({"web": {"results": [
        {"url": "https://openai.com/blog/general-update-from-team/",
         "title": "T", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
    ]}})
    entries = [
        SourceEntry(host="openai.com", path_prefix="/research", name="Research"),
        SourceEntry(host="openai.com", path_prefix="", name="OpenAI (전체)"),  # host-only
    ]
    results = search("AI", entries, api_key="K", session=session)
    assert len(results) == 1  # /blog/... 가 host-only 로 통과 (path row 만 있었으면 차단)


def test_search_count_clamped_to_min() -> None:
    session = FakeSession({"web": {"results": []}})
    search("AI", ["a.com"], api_key="k", num=0, session=session)
    assert session.calls[0]["params"]["count"] == 1


def test_search_falls_back_to_url_when_meta_missing() -> None:
    session = FakeSession(
        {
            "web": {
                "results": [
                    {
                        "title": "T",
                        "url": "https://a.com/2026/05/article-slug-very-detailed/",
                        "description": "s",
                        # meta_url 누락 — url 에서 도메인 추출
                    }
                ]
            }
        }
    )
    results = search("AI", ["a.com"], api_key="k", session=session)
    assert len(results) == 1
    assert results[0].source_domain == "a.com"


def test_search_skips_items_without_url() -> None:
    session = FakeSession(
        {
            "web": {
                "results": [
                    {"title": "no url", "meta_url": {"hostname": "a.com"}},
                    {
                        "title": "ok",
                        "url": "https://a.com/2026/05/article-slug-very-detailed/",
                        "description": "s",
                        "meta_url": {"hostname": "a.com"},
                    },
                ]
            }
        }
    )
    results = search("AI", ["a.com"], api_key="k", session=session)
    assert len(results) == 1
    assert results[0].url == "https://a.com/2026/05/article-slug-very-detailed/"


def test_search_custom_freshness() -> None:
    session = FakeSession({"web": {"results": []}})
    search("AI", ["a.com"], api_key="k", freshness="pw", session=session)
    assert session.calls[0]["params"]["freshness"] == "pw"
