"""검색 조건 load 헬퍼 — DB 우선, yaml fallback.

운영 중에는 admin 페이지에서 DB 에 직접 추가/제거 가능. DB 가 비어있으면
(첫 부팅 또는 의도된 reset) ``domains/<name>/*.yaml`` 의 seed 를 fallback
으로 사용. 이로써 도메인 재사용 (CLAUDE.md §3.1) 과 admin 운영성을 동시 충족.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain_config import DomainConfig
from .search_config_store import (
    KeywordStore,
    SearchSettings,
    SettingsStore,
    SourceStore,
)


@dataclass(frozen=True)
class LoadedConfig:
    keywords: list[str]
    source_domains: list[str]
    source_name_map: dict[str, str]
    settings: SearchSettings


def load_search_config(
    keyword_store: KeywordStore,
    source_store: SourceStore,
    settings_store: SettingsStore,
    fallback: DomainConfig | None = None,
) -> LoadedConfig:
    """3 store + (선택) yaml fallback → LoadedConfig.

    - keywords: DB active 가 있으면 그것, 없고 fallback 있으면 yaml.keywords
    - sources: 동일 규칙 + 사람 친화 매체명 매핑 함께 반환
    - settings: 항상 DB (singleton row 라 절대 비지 않음). 다만 fallback 있어도
      settings 는 DB 가 source of truth.
    """
    db_keywords = keyword_store.list_active()
    if db_keywords:
        keywords = db_keywords
    elif fallback is not None:
        keywords = list(fallback.keywords)
    else:
        keywords = []

    db_sources = source_store.list_active()
    if db_sources:
        domains = [s.domain for s in db_sources]
        name_map = {s.domain: s.name for s in db_sources}
    elif fallback is not None:
        domains = [s.domain for s in fallback.sources]
        name_map = {s.domain: s.name for s in fallback.sources}
    else:
        domains = []
        name_map = {}

    settings = settings_store.get()

    return LoadedConfig(
        keywords=keywords,
        source_domains=domains,
        source_name_map=name_map,
        settings=settings,
    )
