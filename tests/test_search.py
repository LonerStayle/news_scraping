from __future__ import annotations

from typing import Any

import pytest

from ai_news_scraping.search import (
    CSE_MAX_NUM,
    GOOGLE_CSE_ENDPOINT,
    SearchResult,
    build_query,
    search,
)


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

    def get(self, url: str, params: dict[str, Any], timeout: float) -> Any:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
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
            "items": [
                {
                    "title": "AI breakthrough",
                    "link": "https://techcrunch.com/a",
                    "snippet": "snippet 1",
                    "displayLink": "techcrunch.com",
                },
                {
                    "title": "Off-whitelist leak",
                    "link": "https://random.com/x",
                    "snippet": "snippet 2",
                    "displayLink": "random.com",
                },
            ]
        }
    )
    results = search(
        "AI",
        ["techcrunch.com", "wired.com"],
        api_key="k",
        cx="cx",
        session=session,
    )
    assert len(results) == 1
    assert results[0] == SearchResult(
        url="https://techcrunch.com/a",
        title="AI breakthrough",
        snippet="snippet 1",
        source_domain="techcrunch.com",
        keyword="AI",
    )


def test_search_sends_expected_params() -> None:
    session = FakeSession({"items": []})
    search("AI", ["a.com"], api_key="k", cx="cx", session=session)
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == GOOGLE_CSE_ENDPOINT
    p = call["params"]
    assert p["key"] == "k"
    assert p["cx"] == "cx"
    assert p["dateRestrict"] == "d1"
    assert p["sort"] == "date"
    assert p["num"] == CSE_MAX_NUM
    assert "site:a.com" in p["q"]


def test_search_empty_items() -> None:
    results = search("AI", ["a.com"], api_key="k", cx="cx", session=FakeSession({}))
    assert results == []


def test_search_num_clamped_to_max() -> None:
    session = FakeSession({"items": []})
    search("AI", ["a.com"], api_key="k", cx="cx", num=50, session=session)
    assert session.calls[0]["params"]["num"] == CSE_MAX_NUM


def test_search_num_clamped_to_min() -> None:
    session = FakeSession({"items": []})
    search("AI", ["a.com"], api_key="k", cx="cx", num=0, session=session)
    assert session.calls[0]["params"]["num"] == 1


def test_search_skips_items_without_link() -> None:
    session = FakeSession(
        {
            "items": [
                {"title": "no link", "displayLink": "a.com"},
                {
                    "title": "ok",
                    "link": "https://a.com/x",
                    "displayLink": "a.com",
                    "snippet": "s",
                },
            ]
        }
    )
    results = search("AI", ["a.com"], api_key="k", cx="cx", session=session)
    assert len(results) == 1
    assert results[0].url == "https://a.com/x"
