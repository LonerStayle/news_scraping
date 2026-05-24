from __future__ import annotations

from ai_news_scraping.domain_config import DomainConfig, Source
from ai_news_scraping.search_config_loader import (
    LoadedConfig,
    SourceEntry,
    load_search_config,
)
from ai_news_scraping.search_config_store import (
    InMemoryKeywordStore,
    InMemorySettingsStore,
    InMemorySourceStore,
    SearchSettings,
)


def _yaml() -> DomainConfig:
    return DomainConfig(
        keywords=["yaml-kw1", "yaml-kw2"],
        sources=[
            Source(domain="yaml-a.com", name="YAML A"),
            Source(domain="yaml-b.com", name="YAML B"),
        ],
    )


def test_db_empty_uses_yaml_fallback() -> None:
    cfg = load_search_config(
        InMemoryKeywordStore(),
        InMemorySourceStore(),
        InMemorySettingsStore(),
        fallback=_yaml(),
    )
    assert cfg.keywords == ["yaml-kw1", "yaml-kw2"]
    assert cfg.source_domains == ["yaml-a.com", "yaml-b.com"]
    assert cfg.source_name_map == {"yaml-a.com": "YAML A", "yaml-b.com": "YAML B"}
    assert cfg.settings == SearchSettings()


def test_db_non_empty_takes_priority_over_yaml() -> None:
    kw = InMemoryKeywordStore()
    kw.add("db-kw1")
    kw.add("db-kw2")
    src = InMemorySourceStore()
    src.add("db-a.com", "DB A")

    cfg = load_search_config(
        kw, src, InMemorySettingsStore(), fallback=_yaml(),
    )
    assert cfg.keywords == ["db-kw1", "db-kw2"]
    assert cfg.source_domains == ["db-a.com"]
    assert cfg.source_name_map == {"db-a.com": "DB A"}


def test_inactive_db_keywords_are_excluded() -> None:
    kw = InMemoryKeywordStore()
    r1 = kw.add("active-kw")
    r2 = kw.add("inactive-kw")
    kw.set_active(r2.id, False)

    cfg = load_search_config(
        kw, InMemorySourceStore(), InMemorySettingsStore(), fallback=_yaml(),
    )
    # active 만 list_active 가 반환 → DB 가 비어 있지 않으니 yaml fallback X
    assert cfg.keywords == ["active-kw"]
    assert r1 is not None


def test_only_inactive_db_falls_back_to_yaml() -> None:
    """active 가 0건이면 list_active 가 빈 list → yaml fallback 발동."""
    kw = InMemoryKeywordStore()
    r = kw.add("inactive")
    kw.set_active(r.id, False)

    cfg = load_search_config(
        kw, InMemorySourceStore(), InMemorySettingsStore(), fallback=_yaml(),
    )
    assert cfg.keywords == ["yaml-kw1", "yaml-kw2"]


def test_no_fallback_and_empty_db_returns_empty() -> None:
    cfg = load_search_config(
        InMemoryKeywordStore(),
        InMemorySourceStore(),
        InMemorySettingsStore(),
        fallback=None,
    )
    assert cfg.keywords == []
    assert cfg.source_domains == []
    assert cfg.source_name_map == {}


def test_settings_always_from_db() -> None:
    settings = InMemorySettingsStore(SearchSettings(freshness="pm", min_body_len=400))
    cfg = load_search_config(
        InMemoryKeywordStore(),
        InMemorySourceStore(),
        settings,
        fallback=_yaml(),
    )
    assert cfg.settings.freshness == "pm"
    assert cfg.settings.min_body_len == 400


def test_load_search_config_decomposes_source_entries() -> None:
    """SourceEntry 분해 — host+path row 를 host/path/name 으로 깨끗하게 나눈다."""
    kw = InMemoryKeywordStore()
    kw.add("AI")
    src = InMemorySourceStore()
    src.add("openai.com", "OpenAI Blog")
    src.add("openai.com/research", "OpenAI Research")
    src.add("techcrunch.com", "TechCrunch")

    loaded = load_search_config(kw, src, InMemorySettingsStore())
    entries = loaded.source_entries
    assert SourceEntry(host="openai.com", path_prefix="", name="OpenAI Blog") in entries
    assert SourceEntry(
        host="openai.com", path_prefix="/research", name="OpenAI Research"
    ) in entries
    assert SourceEntry(host="techcrunch.com", path_prefix="", name="TechCrunch") in entries


def test_loaded_config_source_domains_dedups_host() -> None:
    """source_domains property 는 host 만 dedup. 같은 host 의 다른 prefix 는 1번만."""
    src = InMemorySourceStore()
    src.add("openai.com", "Blog")
    src.add("openai.com/research", "Research")
    src.add("openai.com/news", "News")
    src.add("techcrunch.com", "TC")

    loaded = load_search_config(
        InMemoryKeywordStore(),
        src,
        InMemorySettingsStore(),
        fallback=_yaml(),  # keywords 채워야 entries 가 안 비음
    )
    assert loaded.source_domains == ["openai.com", "techcrunch.com"]


def test_loaded_config_source_name_map_prefers_host_only_row() -> None:
    """D5: 같은 host 에 host-only row + path row 가 공존하면 host-only 의 name 이 우선."""
    src = InMemorySourceStore()
    src.add("openai.com/research", "Research")  # 먼저 추가
    src.add("openai.com", "Blog (대표)")  # host-only 가 우선해야

    loaded = load_search_config(
        InMemoryKeywordStore(),
        src,
        InMemorySettingsStore(),
        fallback=_yaml(),
    )
    assert loaded.source_name_map["openai.com"] == "Blog (대표)"


def test_loaded_config_is_frozen() -> None:
    """LoadedConfig 는 frozen dataclass — 호출자가 실수로 mutate 못 함."""
    cfg = load_search_config(
        InMemoryKeywordStore(),
        InMemorySourceStore(),
        InMemorySettingsStore(),
        fallback=_yaml(),
    )
    assert isinstance(cfg, LoadedConfig)
    try:
        cfg.keywords = ["x"]  # type: ignore[misc]
        raise AssertionError("frozen=True 여야 함")
    except (AttributeError, TypeError):
        pass
