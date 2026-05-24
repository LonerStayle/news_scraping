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
from urllib.parse import urlparse

import requests

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT_SECONDS = 15.0
BRAVE_MAX_COUNT = 20  # Brave Search 한 호출 최대 결과 수 (count param)
DEFAULT_COUNT = 10
DEFAULT_FRESHNESS = "pd"  # past day

# 카테고리·홈페이지·인덱스 페이지를 차단하는 휴리스틱.
# Brave 가 freshness=pd 로 매일 업데이트되는 카테고리 페이지도 fresh 로
# 분류해 결과에 섞어 보내는 케이스가 빈번 (예: deepmind.google/blog/).
_BLOCKED_FIRST_SEGMENTS = frozenset({
    "category", "categories", "tag", "tags", "topics", "topic",
    "author", "authors", "search", "page", "pages",
})
_MIN_LAST_SEGMENT_LEN = 10  # 개별 기사 slug 는 보통 10자 이상 (kebab-case)


def _looks_like_article_url(url: str) -> bool:
    """카테고리/홈페이지/인덱스 URL 인지 휴리스틱 판정."""
    path = urlparse(url).path.strip("/")
    if not path:
        return False  # 도메인 루트 (예: https://deepmind.google/)
    segments = path.split("/")
    if len(segments) < 2:
        return False  # /news, /blog, /category 같은 단일 segment
    if segments[0].lower() in _BLOCKED_FIRST_SEGMENTS:
        return False  # /category/ai, /tag/ml
    last = segments[-1]
    # /models/, /models/gemini/ 같은 짧은 제품·카테고리 페이지 차단.
    return len(last) >= _MIN_LAST_SEGMENT_LEN


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
    """Brave 쿼리 — host 만 받는다. Brave ``site:`` 가 path 를 거부 (§9-8 함정)."""
    if not keyword.strip():
        raise ValueError("keyword must be non-empty")
    if not source_domains:
        raise ValueError("source_domains must be non-empty")
    sites = " OR ".join(f"site:{d}" for d in source_domains)
    return f'"{keyword}" ({sites})'


def _coerce_to_entries(raw: list[Any]) -> list[Any]:
    """호환층: ``list[str]`` 입력은 host-only ``SourceEntry`` 로 변환.

    기존 caller (pipeline 등) 가 host 리스트만 전달해도 동작. 새 caller 는
    ``SourceEntry`` (host/path_prefix/name) 묶음을 직접 전달.
    """
    if not raw:
        return raw
    if isinstance(raw[0], str):
        # Late import — search_config_loader 가 SourceEntry 를 export. 순환 없음.
        from .search_config_loader import SourceEntry

        return [SourceEntry(host=str(d), path_prefix="", name=str(d)) for d in raw]
    return raw


def search(
    keyword: str,
    source_entries: list[Any],
    *,
    api_key: str,
    num: int = DEFAULT_COUNT,
    freshness: str = DEFAULT_FRESHNESS,
    session: HttpSession | None = None,
) -> list[SearchResult]:
    """One Brave Search call → path-prefix filtered SearchResult list.

    - Brave 쿼리는 host 만 dedup 해 1회 호출 (§9-8 함정 회피).
    - 응답을 받은 후 클라이언트 측에서 row 단위 path-prefix segment-aware 매칭.
    - 같은 host 에 host-only row 와 path row 가 공존하면 host-only 가 우선 (D5).

    Backwards compat: ``source_entries`` 가 ``list[str]`` 이면 host-only entries
    로 자동 변환 — 기존 caller 가 host 리스트만 전달해도 동작 변경 없음.
    """
    sess: HttpSession = (
        session if session is not None else cast(HttpSession, requests.Session())
    )
    entries = _coerce_to_entries(source_entries)
    if not entries:
        raise ValueError("source_entries must be non-empty")

    # host dedup — 같은 host 의 row 가 여럿이라도 Brave 호출은 1번.
    hosts: list[str] = []
    seen: set[str] = set()
    for e in entries:
        h = e.host.lower().removeprefix("www.")
        if h not in seen:
            seen.add(h)
            hosts.append(h)

    headers: dict[str, str] = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params: dict[str, Any] = {
        "q": build_query(keyword, hosts),
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

    # host → 그 host 에 매핑된 entries 들 (다양한 path_prefix).
    host_to_entries: dict[str, list[Any]] = {}
    for e in entries:
        h = e.host.lower().removeprefix("www.")
        host_to_entries.setdefault(h, []).append(e)

    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("url", "")
        if not link:
            continue
        hostname = str(
            (item.get("meta_url") or {}).get("hostname") or _domain_of(link)
        ).lower().removeprefix("www.")
        host_entries = host_to_entries.get(hostname)
        if not host_entries:
            continue
        if not _looks_like_article_url(link):
            continue  # 카테고리/홈페이지/인덱스 페이지 차단

        # path-prefix 매칭 — host-only row (path_prefix == "") 우선 (D5).
        url_path = urlparse(link).path
        host_only = next((e for e in host_entries if e.path_prefix == ""), None)
        matched = host_only or next(
            (e for e in host_entries if _matches_path_prefix(url_path, e.path_prefix)),
            None,
        )
        if matched is None:
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


def _matches_path_prefix(url_path: str, prefix: str) -> bool:
    """segment-aware path-prefix 매칭. ``/research`` 가 ``/researchers`` 와 매치되지 않게.

    빈 prefix (``""`` / ``"/"``) 는 모두 매치 (host-only row, FR-2).
    """
    if not prefix or prefix == "/":
        return True
    norm = prefix.rstrip("/")
    return url_path == norm or url_path.startswith(norm + "/")


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))
