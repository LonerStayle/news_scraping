from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ai_news_scraping.domain_config import DomainConfig, Source, load_domain


def _write_domain(base: Path, keywords_yaml: str, sources_yaml: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "keywords.yaml").write_text(keywords_yaml)
    (base / "sources.yaml").write_text(sources_yaml)


def test_load_domain_reads_keywords_and_sources(tmp_path: Path) -> None:
    _write_domain(
        tmp_path / "topic_x",
        dedent("""\
            keywords:
              - "alpha"
              - "beta"
            """),
        dedent("""\
            sources:
              - domain: a.com
                name: A
              - domain: b.com
                name: B
            """),
    )
    cfg = load_domain("topic_x", root=tmp_path)
    assert cfg == DomainConfig(
        keywords=["alpha", "beta"],
        sources=[Source(domain="a.com", name="A"), Source(domain="b.com", name="B")],
    )


def test_load_ai_news_real_domain() -> None:
    cfg = load_domain("ai_news")
    assert len(cfg.keywords) == 5, "CLAUDE.md §7 fixed 5 keywords"
    assert len(cfg.sources) == 10, "CLAUDE.md §7 fixed 10 sources"
    assert all(s.domain and s.name for s in cfg.sources)
    assert {s.domain for s in cfg.sources} == {
        "techcrunch.com",
        "theverge.com",
        "arstechnica.com",
        "wired.com",
        "venturebeat.com",
        "technologyreview.com",
        "spectrum.ieee.org",
        "openai.com",
        "anthropic.com",
        "deepmind.google",
    }


def test_unknown_domain_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_domain("nonexistent", root=tmp_path)


def test_empty_keywords_raises(tmp_path: Path) -> None:
    _write_domain(
        tmp_path / "bad",
        "keywords: []\n",
        "sources:\n  - domain: a.com\n    name: A\n",
    )
    with pytest.raises(ValueError, match="keywords"):
        load_domain("bad", root=tmp_path)


def test_malformed_source_entry_raises(tmp_path: Path) -> None:
    _write_domain(
        tmp_path / "bad2",
        "keywords:\n  - x\n",
        "sources:\n  - just-a-string\n",
    )
    with pytest.raises(ValueError, match="invalid source"):
        load_domain("bad2", root=tmp_path)
