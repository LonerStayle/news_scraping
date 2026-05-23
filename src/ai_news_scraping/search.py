"""Brave Search API wrapper — 3위일체 검색.

키워드 + 매체 화이트리스트 + 최신순 (CLAUDE.md §3.1).
키워드당 1 호출 — 매체는 `site:(d1 OR d2 ...)` 로 한 쿼리에 묶어 Brave Free
quota (월 2,000) 안에서 운영한다 (CLAUDE.md §6). 일 5 호출 × 30일 = 150 호출.

이전: Google Custom Search API. 신규 Cloud 프로젝트에서 PERMISSION_DENIED
가 빈번해 운영 신뢰도가 낮아 교체.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

import requests

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT_SECONDS = 15.0
BRAVE_MAX_COUNT = 20  # Brave Search 한 호출 최대 결과 수 (count param)
DEFAULT_COUNT = 10
DEFAULT_FRESHNESS = "pd"  # past day


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    source_domain: str
    keyword: str


class HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> requests.Response: ...


def build_query(keyword: str, source_domains: list[str]) -> str:
    if not keyword.strip():
        raise ValueError("keyword must be non-empty")
    if not source_domains:
        raise ValueError("source_domains must be non-empty")
    sites = " OR ".join(f"site:{d}" for d in source_domains)
    return f'"{keyword}" ({sites})'


def search(
    keyword: str,
    source_domains: list[str],
    *,
    api_key: str,
    num: int = DEFAULT_COUNT,
    freshness: str = DEFAULT_FRESHNESS,
    session: HttpSession | None = None,
) -> list[SearchResult]:
    """One Brave Search call → whitelisted SearchResult list.

    - ``freshness="pd"`` (past day) = "최신순" 축. ``pw`` / ``pm`` / ``py``
      또는 ISO 날짜 범위 지원.
    - Brave 의 ``meta_url.hostname`` 으로 화이트리스트 재필터 — 검색엔진이
      site: 필터 안에서 가끔 다른 도메인을 섞어주는 케이스 방어.
    """
    sess: HttpSession = (
        session if session is not None else cast(HttpSession, requests.Session())
    )
    headers: dict[str, str] = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params: dict[str, Any] = {
        "q": build_query(keyword, source_domains),
        "count": _clamp(num, 1, BRAVE_MAX_COUNT),
        "freshness": freshness,
    }
    resp = sess.get(
        BRAVE_SEARCH_ENDPOINT,
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    items: list[dict[str, Any]] = (payload.get("web") or {}).get("results") or []

    whitelist = {d.lower() for d in source_domains}
    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("url", "")
        hostname = str(
            (item.get("meta_url") or {}).get("hostname")
            or _domain_of(link)
        ).lower()
        # `meta_url.hostname` 은 종종 "www." prefix 포함 — 화이트리스트 매칭 위해 제거
        hostname = hostname.removeprefix("www.")
        if not link or hostname not in whitelist:
            continue
        results.append(
            SearchResult(
                url=link,
                title=str(item.get("title", "")),
                snippet=str(item.get("description", "")),
                source_domain=hostname,
                keyword=keyword,
            )
        )
    return results


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower().removeprefix("www.")


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))
