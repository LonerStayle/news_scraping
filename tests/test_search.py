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


# ─────────── discover_paths (Phase H — 자동 path 추천) ───────────


def _payload_with_urls(host: str, paths: list[str]) -> dict[str, Any]:
    """헬퍼: 같은 host 의 다양한 path URL 들을 Brave 응답 payload 로 변환."""
    return {
        "web": {
            "results": [
                {
                    "title": f"T-{i}",
                    "url": f"https://{host}{p}",
                    "description": "snippet",
                    "meta_url": {"hostname": host},
                }
                for i, p in enumerate(paths)
            ]
        }
    }


def test_discover_paths_aggregates_by_first_segment() -> None:
    """OpenAI 실제 사고 시나리오: /index 13건 / /research 3건 / /blog 1건."""
    from ai_news_scraping.search import PathSuggestion, discover_paths

    paths = (
        [f"/index/openai-on-aws-{i}/" for i in range(13)]
        + [f"/research/paper-{i}/" for i in range(3)]
        + ["/blog/spring-update/"]
    )
    session = FakeSession(_payload_with_urls("openai.com", paths))
    suggestions = discover_paths(
        "openai.com", "AI", api_key="K", session=session
    )

    # frequency 순 정렬
    assert len(suggestions) == 3
    assert isinstance(suggestions[0], PathSuggestion)
    assert suggestions[0].prefix == "/index"
    assert suggestions[0].count == 13
    assert suggestions[0].percentage == pytest.approx(76.5, abs=0.1)
    assert suggestions[0].sample_url == "https://openai.com/index/openai-on-aws-0/"
    assert suggestions[1].prefix == "/research"
    assert suggestions[1].count == 3
    assert suggestions[2].prefix == "/blog"
    assert suggestions[2].count == 1


def test_discover_paths_ignores_other_hosts() -> None:
    """Brave 가 다른 매체 결과 섞어 보내도 host 외 row 는 집계 X."""
    from ai_news_scraping.search import discover_paths

    session = FakeSession({
        "web": {
            "results": [
                {"url": "https://openai.com/index/a-real-article-here/",
                 "title": "T", "description": "s",
                 "meta_url": {"hostname": "openai.com"}},
                {"url": "https://techcrunch.com/2026/05/leak-article/",
                 "title": "T", "description": "s",
                 "meta_url": {"hostname": "techcrunch.com"}},
                {"url": "https://wired.com/story/random/",
                 "title": "T", "description": "s",
                 "meta_url": {"hostname": "wired.com"}},
            ]
        }
    })
    suggestions = discover_paths(
        "openai.com", "AI", api_key="K", session=session
    )
    assert len(suggestions) == 1
    assert suggestions[0].prefix == "/index"
    assert suggestions[0].count == 1
    assert suggestions[0].percentage == pytest.approx(100.0, abs=0.1)


def test_discover_paths_ignores_root_url() -> None:
    """도메인 루트 (/ 만) 는 글이 아니라 홈 페이지 — 집계 무시."""
    from ai_news_scraping.search import discover_paths

    session = FakeSession(_payload_with_urls("a.com", [
        "/", "", "/index/article-one/", "/index/article-two/",
    ]))
    suggestions = discover_paths(
        "a.com", "AI", api_key="K", session=session
    )
    assert len(suggestions) == 1
    assert suggestions[0].prefix == "/index"
    assert suggestions[0].count == 2


def test_discover_paths_strips_www_prefix() -> None:
    """www.host 와 host 는 동일 매체로 묶음."""
    from ai_news_scraping.search import discover_paths

    session = FakeSession({
        "web": {
            "results": [
                {"url": "https://www.theverge.com/2026/05/ai-policy-story/",
                 "title": "T", "description": "s",
                 "meta_url": {"hostname": "www.theverge.com"}},
                {"url": "https://theverge.com/2026/05/another-story/",
                 "title": "T", "description": "s",
                 "meta_url": {"hostname": "theverge.com"}},
            ]
        }
    })
    suggestions = discover_paths(
        "theverge.com", "AI", api_key="K", session=session
    )
    # /2026 prefix 1개 (둘 다 같은 첫 segment)
    assert len(suggestions) == 1
    assert suggestions[0].count == 2


def test_discover_paths_empty_response() -> None:
    from ai_news_scraping.search import discover_paths

    session = FakeSession({"web": {"results": []}})
    suggestions = discover_paths(
        "openai.com", "AI", api_key="K", session=session
    )
    assert suggestions == []


def test_discover_paths_sends_correct_brave_query() -> None:
    from ai_news_scraping.search import discover_paths

    session = FakeSession({"web": {"results": []}})
    discover_paths("openai.com", "AI", api_key="K1", session=session)
    call = session.calls[0]
    assert call["url"] == BRAVE_SEARCH_ENDPOINT
    assert call["headers"]["X-Subscription-Token"] == "K1"
    assert "site:openai.com" in call["params"]["q"]
    assert "AI" in call["params"]["q"]
    # default freshness: pm (path 발견 목적이라 넓게)
    assert call["params"]["freshness"] == "pm"
    assert call["params"]["count"] == 20


def test_discover_paths_rejects_empty_host() -> None:
    from ai_news_scraping.search import discover_paths

    with pytest.raises(ValueError, match="host"):
        discover_paths("", "AI", api_key="K", session=FakeSession({}))


def test_discover_paths_rejects_empty_keyword() -> None:
    from ai_news_scraping.search import discover_paths

    with pytest.raises(ValueError, match="keyword"):
        discover_paths("a.com", "  ", api_key="K", session=FakeSession({}))


def test_discover_paths_top_n_limit() -> None:
    """top N (default 5) 만 반환 — 너무 분산된 매체 노이즈 차단."""
    from ai_news_scraping.search import discover_paths

    paths = [f"/seg{i}/article/" for i in range(10)]  # 10 unique first segments
    session = FakeSession(_payload_with_urls("a.com", paths))
    suggestions = discover_paths(
        "a.com", "AI", api_key="K", session=session, top_n=5
    )
    assert len(suggestions) == 5


def test_discover_paths_stable_sort_on_tie() -> None:
    """같은 count 면 처음 발견된 prefix 우선 — 결과 결정적."""
    from ai_news_scraping.search import discover_paths

    paths = ["/alpha/a/", "/beta/b/", "/alpha/c/", "/beta/d/"]
    session = FakeSession(_payload_with_urls("a.com", paths))
    suggestions = discover_paths(
        "a.com", "AI", api_key="K", session=session
    )
    assert len(suggestions) == 2
    assert suggestions[0].count == 2
    assert suggestions[1].count == 2
    # tie → 등장 순서 (/alpha 먼저)
    assert suggestions[0].prefix == "/alpha"
    assert suggestions[1].prefix == "/beta"
