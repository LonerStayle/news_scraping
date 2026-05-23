"""trafilatura 기반 본문 추출 wrapper.

검색 API 는 URL + snippet 만 주므로 본문은 별도로 fetch + 추출한다.
trafilatura 가 매체별 HTML 구조 차이를 자동 처리한다 (CLAUDE.md §6).
실패 시 ExtractionError 를 발생시키고, 호출측은 화이트리스트에서 해당
매체를 제외하거나 단순히 그 기사를 skip 하는 정책을 적용한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
import trafilatura

MIN_BODY_LEN = 200
RAW_EXCERPT_LEN = 500
FETCH_TIMEOUT_SECONDS = 15.0

# trafilatura 의 기본 User-Agent 는 일부 매체 (openai.com, anthropic.com 등)
# 가 봇으로 보고 403 차단함. 정상 브라우저 UA 로 우회.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_logger = logging.getLogger(__name__)


def fetch_html_with_browser_ua(url: str) -> str | None:
    """requests + 정상 브라우저 UA 로 HTML fetch. 4xx/5xx → None."""
    try:
        resp = requests.get(
            url, headers=BROWSER_HEADERS, timeout=FETCH_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.RequestException as e:
        _logger.info("fetch error: %s (%s)", url, e)
        return None
    if resp.status_code != 200:
        _logger.info("fetch non-200: %s → %d", url, resp.status_code)
        return None
    return resp.text


@dataclass(frozen=True)
class ExtractedArticle:
    url: str
    title: str
    body_text: str
    raw_html_excerpt: str
    published_at: str | None
    source_domain: str


class ExtractionError(Exception):
    """Body fetch or extraction failed — caller may skip or denylist."""


HtmlFetcher = Callable[[str], str | None]
BodyExtractor = Callable[[str], str | None]
MetaExtractor = Callable[[str], Any]


def extract(
    url: str,
    *,
    fetch_html: HtmlFetcher | None = None,
    extract_body: BodyExtractor | None = None,
    extract_meta: MetaExtractor | None = None,
    min_body_len: int = MIN_BODY_LEN,
) -> ExtractedArticle:
    """Fetch HTML, run trafilatura, return ExtractedArticle (or raise)."""
    fetcher: HtmlFetcher = fetch_html if fetch_html is not None else fetch_html_with_browser_ua
    body_ex: BodyExtractor = (
        extract_body if extract_body is not None else trafilatura.extract
    )
    meta_ex: MetaExtractor = (
        extract_meta if extract_meta is not None else trafilatura.extract_metadata
    )

    html = fetcher(url)
    if not html:
        raise ExtractionError(f"fetch failed: {url}")

    body = body_ex(html)
    body_len = len(body.strip()) if body else 0
    if body_len < min_body_len:
        raise ExtractionError(
            f"body too short (len={body_len}, min={min_body_len}): {url}"
        )
    assert body is not None  # narrowed by body_len check above

    meta = meta_ex(html)
    title = getattr(meta, "title", None) or ""
    published_at = getattr(meta, "date", None)

    return ExtractedArticle(
        url=url,
        title=str(title),
        body_text=body.strip(),
        raw_html_excerpt=html[:RAW_EXCERPT_LEN],
        published_at=str(published_at) if published_at else None,
        source_domain=_domain_of(url),
    )


def _domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc.removeprefix("www.")
