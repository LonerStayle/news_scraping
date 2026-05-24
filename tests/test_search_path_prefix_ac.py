"""search-path-prefix 피처의 AC-1..5 end-to-end 검증.

각 test 가 PRD §6 의 AC 와 1:1 매핑. 빠른 회귀 게이트로 활용.
"""

from __future__ import annotations

from typing import Any

import pytest

from ai_news_scraping.search import SearchResult, search
from ai_news_scraping.search_config_loader import SourceEntry
from ai_news_scraping.search_config_store import (
    InMemorySourceStore,
    _normalize_domain,
)


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._payload = {"web": {"results": results}}
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> Any:
        self.calls.append({"url": url, "params": params})
        return _FakeResp(self._payload)


def _mk(url: str, host: str) -> dict[str, Any]:
    """짧은 mock 결과 dict 빌더 — slug 는 article URL 휴리스틱 통과하도록 충분히 길게."""
    return {
        "url": url, "title": "T", "description": "d",
        "meta_url": {"hostname": host},
    }


# ─────────── AC-1 ───────────


def test_AC1_host_only_row_lets_all_results_through() -> None:
    """AC-1: openai.com row 만 등록 시, 검색 결과의 모든 openai.com/... URL 통과."""
    session = _FakeSession([
        _mk("https://openai.com/research/papers/2026/new-reasoning-paper", "openai.com"),
        _mk("https://openai.com/news/funding-round-details-2026", "openai.com"),
        _mk("https://openai.com/blog/general-update-spring-2026", "openai.com"),
    ])
    entries = [SourceEntry(host="openai.com", path_prefix="", name="OpenAI")]
    results = search("AI", entries, api_key="K", session=session)
    assert len(results) == 3


# ─────────── AC-2 ───────────


def test_AC2_path_prefix_filters_other_sections() -> None:
    """AC-2: openai.com/research row 등록 시, /research 만 통과, /news 차단."""
    session = _FakeSession([
        _mk("https://openai.com/research/papers/2026/new-reasoning-paper", "openai.com"),
        _mk("https://openai.com/news/funding-round-details-2026", "openai.com"),
    ])
    entries = [SourceEntry(host="openai.com", path_prefix="/research", name="Research")]
    results = search("AI", entries, api_key="K", session=session)
    urls = {r.url for r in results}
    assert "https://openai.com/research/papers/2026/new-reasoning-paper" in urls
    assert "https://openai.com/news/funding-round-details-2026" not in urls


# ─────────── AC-3 ───────────


def test_AC3_multiple_prefixes_both_active() -> None:
    """AC-3: /research + /news 두 row 등록 시, 두 prefix 결과 모두 통과."""
    session = _FakeSession([
        _mk("https://openai.com/research/papers/2026/new-reasoning-paper", "openai.com"),
        _mk("https://openai.com/news/funding-round-details-2026", "openai.com"),
        _mk("https://openai.com/blog/general-update-spring-2026", "openai.com"),
    ])
    entries = [
        SourceEntry(host="openai.com", path_prefix="/research", name="Research"),
        SourceEntry(host="openai.com", path_prefix="/news", name="News"),
    ]
    results = search("AI", entries, api_key="K", session=session)
    urls = {r.url for r in results}
    assert "https://openai.com/research/papers/2026/new-reasoning-paper" in urls
    assert "https://openai.com/news/funding-round-details-2026" in urls
    assert "https://openai.com/blog/general-update-spring-2026" not in urls


# ─────────── AC-4 ───────────


def test_AC4_normalize_domain_rejects_scheme() -> None:
    """AC-4: admin 입력에 https:// 스킴 포함 시 ValueError (400 reject)."""
    with pytest.raises(ValueError):
        _normalize_domain("https://openai.com")


def test_AC4_admin_source_store_rejects_invalid_input() -> None:
    """AC-4: SourceStore.add 도 _normalize_domain 통해 같은 reject 정책."""
    s = InMemorySourceStore()
    with pytest.raises(ValueError):
        s.add("https://openai.com", "Bad")


# ─────────── AC-5 ───────────


def test_AC5_existing_host_only_row_unchanged() -> None:
    """AC-5: 기존 host-only row (yaml seed 형태) 동작 회귀 0.

    sources.yaml 의 10개 매체가 모두 host-only — search() 가 list[str] (legacy)
    또는 list[SourceEntry] (신규) 둘 다 받아 동일 결과.
    """
    payload = [
        _mk("https://techcrunch.com/2026/05/ai-launch-news-today", "techcrunch.com"),
    ]
    # 기존 caller 형태 (str list)
    legacy_session = _FakeSession(payload)
    legacy_results = search("AI", ["techcrunch.com"], api_key="K", session=legacy_session)
    # 신규 caller 형태 (SourceEntry list)
    new_session = _FakeSession(payload)
    new_results = search(
        "AI",
        [SourceEntry(host="techcrunch.com", path_prefix="", name="TechCrunch")],
        api_key="K",
        session=new_session,
    )
    assert [r.url for r in legacy_results] == [r.url for r in new_results]
    assert len(legacy_results) == 1


# ─────────── 보너스: D5 (넓은 우선) 명시 ───────────


def test_D5_host_only_takes_priority_over_path_row() -> None:
    """D5: 같은 host 에 host-only + path row 공존 시 host-only 우선 (모두 통과)."""
    session = _FakeSession([
        _mk("https://openai.com/blog/general-update-spring-2026", "openai.com"),
    ])
    entries = [
        SourceEntry(host="openai.com", path_prefix="/research", name="Research"),
        SourceEntry(host="openai.com", path_prefix="", name="OpenAI (전체)"),
    ]
    results: list[SearchResult] = search("AI", entries, api_key="K", session=session)
    assert len(results) == 1
