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
# 마지막 segment 의 최소 길이. 예전엔 10 이었지만 운영 로그에서 정상 글
# (예: anthropic.com/news/anthropic-nec, ai.meta.com/blog/llama-x) 도 다수
# 차단되어 5 로 완화. 너무 작으면 /models/, /api/ 같은 product 페이지 통과
# 위험이 있어 첫 segment 가 'product'/'docs'/'api' 류면 별도 차단.
_MIN_LAST_SEGMENT_LEN = 5
_BLOCKED_PRODUCT_SEGMENTS = frozenset({
    "product", "products", "docs", "doc", "api", "apis", "pricing",
    "careers", "about", "contact", "support", "help", "legal", "privacy",
    "terms", "events", "event",
})


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
    if segments[0].lower() in _BLOCKED_PRODUCT_SEGMENTS:
        return False  # /product/claude-cowork, /events/aws-summit, /careers/...
    last = segments[-1]
    return len(last) >= _MIN_LAST_SEGMENT_LEN


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    source_domain: str
    keyword: str


@dataclass(frozen=True)
class PathSuggestion:
    """admin 자동 path 추천 결과 — `discover_paths()` 반환 항목.

    매체 등록 시 사용자가 정확한 path 패턴을 모를 때, Brave 응답 URL 들의
    첫 segment frequency 를 집계해 추천. 예: openai.com → `/index` 65%
    (사용자가 직관적으로 입력하는 `/news` 가 아니라 실제 글이 색인된 path).
    """

    prefix: str  # 예: "/index", "/research"
    count: int
    percentage: float  # 0~100. 1 decimal 권장.
    sample_url: str  # 사용자 검증용 — 추천 prefix 의 첫 URL


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
    """Brave 쿼리 — host 만 받는다.

    ⚠️ HANDOFF.md §9-8 함정: Brave Search 의 ``site:`` 연산자는 host 만 허용.
    ``site:openai.com/research`` 같은 path 포함 형태는 **422 Unprocessable Entity**
    로 거부됨 (실제 사고: 2026-05-24). path 필터는 클라이언트 측 ``_matches_path_prefix``
    에서 처리. 이 함수는 host 만 받음을 호출자 책임으로 가정.
    """
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

    # 디버그 카운터 — 어느 단계에서 결과가 잘리는지 가시화 (대표님 운영 진단용).
    raw_host_dist: dict[str, int] = {}
    rejected_unknown_host: dict[str, int] = {}
    rejected_non_article: dict[str, int] = {}
    rejected_path_mismatch: dict[str, list[str]] = {}

    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("url", "")
        if not link:
            continue
        hostname = str(
            (item.get("meta_url") or {}).get("hostname") or _domain_of(link)
        ).lower().removeprefix("www.")
        raw_host_dist[hostname] = raw_host_dist.get(hostname, 0) + 1

        host_entries = host_to_entries.get(hostname)
        if not host_entries:
            rejected_unknown_host[hostname] = rejected_unknown_host.get(hostname, 0) + 1
            continue
        if not _looks_like_article_url(link):
            rejected_non_article[hostname] = rejected_non_article.get(hostname, 0) + 1
            continue

        # path-prefix 매칭 — host-only row (path_prefix == "") 우선 (D5).
        url_path = urlparse(link).path
        host_only = next((e for e in host_entries if e.path_prefix == ""), None)
        matched = host_only or next(
            (e for e in host_entries if _matches_path_prefix(url_path, e.path_prefix)),
            None,
        )
        if matched is None:
            # path 필터에서 잘린 URL — 진단 정보로 첫 3개 URL 저장.
            samples = rejected_path_mismatch.setdefault(hostname, [])
            if len(samples) < 3:
                samples.append(url_path)
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

    # 디버그 로그 — Brave 응답 분포 + 단계별 reject 카운트.
    if items:
        import logging as _log
        _logger = _log.getLogger(__name__)
        raw_pairs = sorted(raw_host_dist.items(), key=lambda x: -x[1])
        raw_str = ", ".join(f"{h}={n}" for h, n in raw_pairs)
        _logger.info("Brave RAW [%s] %d items | %s", keyword, len(items), raw_str)
        if rejected_unknown_host:
            _logger.info("  └ unknown_host: %s", dict(rejected_unknown_host))
        if rejected_non_article:
            _logger.info("  └ non_article (휴리스틱 차단): %s", dict(rejected_non_article))
        if rejected_path_mismatch:
            for host, samples in rejected_path_mismatch.items():
                _logger.info("  └ path_mismatch %s (%d): 예시 paths=%s",
                             host, len(samples), samples)
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


def _first_segment(url: str) -> str | None:
    """URL → 첫 path segment (`"/index"` 형식) 또는 None (root / empty)."""
    path = urlparse(url).path.strip("/")
    if not path:
        return None
    return "/" + path.split("/")[0].lower()


def discover_paths(
    host: str,
    keyword: str,
    *,
    api_key: str,
    num: int = 20,
    freshness: str = "pm",
    top_n: int = 5,
    session: HttpSession | None = None,
) -> list[PathSuggestion]:
    """Brave 1회 호출로 host 매체의 실제 글 path 패턴 발견.

    옵션 A (HANDOFF.md §12-C) — 사용자가 도메인만 입력해도 admin 이 자동으로
    실제 글이 색인된 path prefix 추천. 운영 사고 (2026-05-25, 14 매체 active
    인데 한 매체로 92% 쏠림) 의 근본 해결.

    - Brave 응답 URL 들의 **첫 path segment** frequency 집계
    - 같은 host 의 row 만 집계 (Brave 가 다른 매체 결과 섞을 수 있음)
    - 도메인 루트 (`/`) 는 글이 아니라 홈 페이지로 간주 — 집계 무시
    - sort: count DESC, 등장 순서 (Python dict 보존 + sorted stable)
    """
    if not host.strip():
        raise ValueError("host must be non-empty")
    if not keyword.strip():
        raise ValueError("keyword must be non-empty")

    sess: HttpSession = (
        session if session is not None else cast(HttpSession, requests.Session())
    )
    normalized_host = host.lower().removeprefix("www.")
    params: dict[str, Any] = {
        "q": build_query(keyword, [normalized_host]),
        "count": _clamp(num, 1, BRAVE_MAX_COUNT),
        "freshness": freshness,
    }
    headers: dict[str, str] = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
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

    # 첫 segment → (count, first_sample_url) — Python dict 가 등장 순서 보존
    seg_counts: dict[str, list[Any]] = {}
    total_host_rows = 0
    for item in items:
        link = item.get("url") or ""
        if not link:
            continue
        hostname = str(
            (item.get("meta_url") or {}).get("hostname") or _domain_of(link)
        ).lower().removeprefix("www.")
        if hostname != normalized_host:
            continue
        total_host_rows += 1
        seg = _first_segment(link)
        if seg is None:
            continue  # 루트 URL — 글 아님
        if seg not in seg_counts:
            seg_counts[seg] = [0, link]
        seg_counts[seg][0] += 1

    if total_host_rows == 0:
        return []

    # count DESC, tie 시 등장 순서 (Python sorted 는 stable).
    sorted_entries = sorted(
        seg_counts.items(),
        key=lambda kv: -kv[1][0],
    )
    suggestions: list[PathSuggestion] = []
    for prefix, (count, sample) in sorted_entries[:top_n]:
        suggestions.append(
            PathSuggestion(
                prefix=prefix,
                count=count,
                percentage=round(count / total_host_rows * 100, 1),
                sample_url=str(sample),
            )
        )
    return suggestions
