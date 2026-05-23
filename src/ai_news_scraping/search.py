"""Google Custom Search API wrapper — 3위일체 검색.

키워드 + 매체 화이트리스트 + 최신순 (CLAUDE.md §3.1).
키워드당 1 호출 — 매체는 `site:(d1 OR d2 ...)` 로 한 쿼리에 묶어 무료 quota
(일 100) 안에서 운영한다 (CLAUDE.md §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

import requests

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
DEFAULT_TIMEOUT_SECONDS = 15.0
CSE_MAX_NUM = 10  # Custom Search API 한 호출 최대 결과 수


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    source_domain: str
    keyword: str


class HttpSession(Protocol):
    def get(
        self, url: str, params: dict[str, Any], timeout: float
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
    cx: str,
    num: int = CSE_MAX_NUM,
    date_restrict: str = "d1",
    session: HttpSession | None = None,
) -> list[SearchResult]:
    """One Google CSE call → whitelisted SearchResult list.

    - `dateRestrict="d1"` + `sort="date"` = "최신순" 축.
    - Off-whitelist 결과는 displayLink 로 다시 걸러낸다 (Google 이 site: 필터
      안에서 가끔 다른 도메인을 섞어주는 케이스 방어).
    """
    sess: HttpSession = session if session is not None else cast(HttpSession, requests.Session())
    params: dict[str, Any] = {
        "key": api_key,
        "cx": cx,
        "q": build_query(keyword, source_domains),
        "num": _clamp(num, 1, CSE_MAX_NUM),
        "dateRestrict": date_restrict,
        "sort": "date",
    }
    resp = sess.get(GOOGLE_CSE_ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    items: list[dict[str, Any]] = payload.get("items") or []

    whitelist = {d.lower() for d in source_domains}
    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("link", "")
        display_link = str(item.get("displayLink") or "").lower()
        if not link or display_link not in whitelist:
            continue
        results.append(
            SearchResult(
                url=link,
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
                source_domain=display_link,
                keyword=keyword,
            )
        )
    return results


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))
