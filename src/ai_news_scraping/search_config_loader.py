"""검색 조건 load 헬퍼 — DB 우선, yaml fallback.

운영 중에는 admin 페이지에서 DB 에 직접 추가/제거 가능. DB 가 비어있으면
(첫 부팅 또는 의도된 reset) ``domains/<name>/*.yaml`` 의 seed 를 fallback
으로 사용. 이로써 도메인 재사용 (CLAUDE.md §3.1) 과 admin 운영성을 동시 충족.

`SourceEntry` 분해: `search_sources.domain` 값이 host (예: `openai.com`) 또는
host/path prefix (예: `openai.com/research`) 둘 다 받기 때문에, 호출자가 매번
파싱하지 않도록 LoadedConfig 단에서 host/path_prefix/name 으로 깨끗하게 나눠 준다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain_config import DomainConfig
from .search_config_store import (
    KeywordStore,
    SearchSettings,
    SettingsStore,
    SourceStore,
    _split_host_path,
)


@dataclass(frozen=True)
class SourceEntry:
    """매체 row 한 줄 분해.

    - host = Brave Search 의 ``site:`` 키
    - path_prefix = 클라이언트 측 path 필터 키 (`""` 면 매체 전체 통과)
    - name = 출처 링크에 노출될 사람 친화 매체명
    """
    host: str
    path_prefix: str
    name: str


@dataclass(frozen=True)
class LoadedConfig:
    keywords: list[str]
    source_entries: list[SourceEntry]
    settings: SearchSettings

    @property
    def source_domains(self) -> list[str]:
        """역호환 — caller 가 host 리스트만 원할 때. dedup 적용."""
        seen: set[str] = set()
        out: list[str] = []
        for e in self.source_entries:
            if e.host not in seen:
                seen.add(e.host)
                out.append(e.host)
        return out

    @property
    def source_name_map(self) -> dict[str, str]:
        """역호환 — host → name 매핑.

        D5 (넓은 우선): 같은 host 에 host-only row 가 있으면 그게 우선.
        없으면 첫 path row 의 name 사용.
        """
        m: dict[str, str] = {}
        for e in self.source_entries:
            if e.path_prefix == "" and e.host not in m:
                m[e.host] = e.name
        for e in self.source_entries:
            if e.host not in m:
                m[e.host] = e.name
        return m


def load_search_config(
    keyword_store: KeywordStore,
    source_store: SourceStore,
    settings_store: SettingsStore,
    fallback: DomainConfig | None = None,
) -> LoadedConfig:
    """3 store + (선택) yaml fallback → LoadedConfig.

    - keywords: DB active 가 있으면 그것, 없고 fallback 있으면 yaml.keywords
    - sources: DB active 가 있으면 그것, 없고 fallback 있으면 yaml. 각 row 의
      ``domain`` 값을 ``(host, path_prefix)`` 로 분해해 ``SourceEntry`` 리스트로 반환.
    - settings: 항상 DB (singleton row 라 절대 비지 않음).
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
        rows = [(s.domain, s.name) for s in db_sources]
    elif fallback is not None:
        rows = [(s.domain, s.name) for s in fallback.sources]
    else:
        rows = []

    entries: list[SourceEntry] = []
    for domain_raw, name in rows:
        host, path = _split_host_path(domain_raw)
        entries.append(SourceEntry(host=host, path_prefix=path, name=name))

    settings = settings_store.get()

    return LoadedConfig(
        keywords=keywords,
        source_entries=entries,
        settings=settings,
    )
