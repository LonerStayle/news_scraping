from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_news_scraping.extract import ExtractionError, extract


@dataclass
class FakeMeta:
    title: str | None = None
    date: str | None = None


def test_happy_path() -> None:
    html = "<html><body>" + "x" * 600 + "</body></html>"
    article = extract(
        "https://techcrunch.com/article/123",
        fetch_html=lambda u: html,
        extract_body=lambda h: "long body text " * 50,
        extract_meta=lambda h: FakeMeta(title="Hello AI", date="2026-05-23"),
    )
    assert article.url == "https://techcrunch.com/article/123"
    assert article.title == "Hello AI"
    assert article.published_at == "2026-05-23"
    assert article.source_domain == "techcrunch.com"
    assert article.body_text.startswith("long body text")
    assert article.raw_html_excerpt.startswith("<html>")
    assert len(article.raw_html_excerpt) <= 500


def test_fetch_failure_raises() -> None:
    with pytest.raises(ExtractionError, match="fetch failed"):
        extract("https://x.com/a", fetch_html=lambda u: None)


def test_empty_html_raises() -> None:
    with pytest.raises(ExtractionError, match="fetch failed"):
        extract("https://x.com/a", fetch_html=lambda u: "")


def test_body_too_short_raises() -> None:
    with pytest.raises(ExtractionError, match="body too short"):
        extract(
            "https://x.com/a",
            fetch_html=lambda u: "<html></html>",
            extract_body=lambda u: "short",
        )


def test_extracted_body_none_raises() -> None:
    with pytest.raises(ExtractionError, match="body too short"):
        extract(
            "https://x.com/a",
            fetch_html=lambda u: "<html></html>",
            extract_body=lambda u: None,
        )


def test_no_metadata_fields() -> None:
    article = extract(
        "https://x.com/a",
        fetch_html=lambda u: "<html></html>",
        extract_body=lambda u: "x" * 600,
        extract_meta=lambda u: None,
    )
    assert article.title == ""
    assert article.published_at is None


def test_domain_strips_www() -> None:
    article = extract(
        "https://www.theverge.com/path/x",
        fetch_html=lambda u: "<html></html>",
        extract_body=lambda u: "x" * 600,
        extract_meta=lambda u: None,
    )
    assert article.source_domain == "theverge.com"


def test_min_body_len_override() -> None:
    article = extract(
        "https://x.com/a",
        fetch_html=lambda u: "<html></html>",
        extract_body=lambda u: "short",
        extract_meta=lambda u: None,
        min_body_len=3,
    )
    assert article.body_text == "short"
