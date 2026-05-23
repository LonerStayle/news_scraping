from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ai_news_scraping.extract import ExtractedArticle, ExtractionError
from ai_news_scraping.mail import MailSendResult
from ai_news_scraping.pipeline import (
    PipelineDeps,
    PipelineParams,
    PipelineResult,
    run,
)
from ai_news_scraping.search import SearchResult
from ai_news_scraping.store import InMemoryArticleStore
from ai_news_scraping.summarize import SummaryInput, SummaryOutput

FIXED_NOW = datetime(2026, 5, 23, 0, 40, 0, tzinfo=UTC)


def _now() -> datetime:
    return FIXED_NOW


def _params(**overrides: Any) -> PipelineParams:
    defaults: dict[str, Any] = {
        "keywords": ["kw1"],
        "source_domains": ["a.com"],
        "subscribers": ["x@x.com"],
        "brave_search_api_key": "BSK",
        "gemini_api_key": "G",
        "gemini_model": "gemini-2.5-flash",
        "gmail_user": "me@gmail.com",
        "gmail_password": "P",
        "dry_run": False,
    }
    defaults.update(overrides)
    return PipelineParams(**defaults)


def _result_factory(
    url: str = "https://a.com/x",
    keyword: str = "kw1",
    domain: str = "a.com",
) -> SearchResult:
    return SearchResult(
        url=url,
        title=f"T-{url}",
        snippet="s",
        source_domain=domain,
        keyword=keyword,
    )


def _extracted_for(url: str, *, domain: str = "a.com") -> ExtractedArticle:
    return ExtractedArticle(
        url=url,
        title=f"Title {url}",
        body_text="english body " * 50,
        raw_html_excerpt="<html>",
        published_at="2026-05-23",
        source_domain=domain,
    )


# ────────── Fake building blocks ──────────


@dataclass
class FakeSearchFn:
    by_keyword: dict[str, list[SearchResult]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    raise_on: set[str] = field(default_factory=set)

    def __call__(
        self,
        keyword: str,
        source_domains: list[str],
        *,
        api_key: str,
        num: int = 10,
        freshness: str = "pd",
    ) -> list[SearchResult]:
        self.calls.append({
            "keyword": keyword,
            "source_domains": source_domains,
            "num": num,
            "freshness": freshness,
        })
        if keyword in self.raise_on:
            raise RuntimeError(f"search failed for {keyword}")
        return list(self.by_keyword.get(keyword, []))


@dataclass
class FakeExtractFn:
    by_url: dict[str, ExtractedArticle] = field(default_factory=dict)
    raise_on: set[str] = field(default_factory=set)
    crash_on: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def __call__(self, url: str) -> ExtractedArticle:
        self.calls.append(url)
        if url in self.crash_on:
            raise RuntimeError("crash")
        if url in self.raise_on:
            raise ExtractionError(f"body too short: {url}")
        if url in self.by_url:
            return self.by_url[url]
        return _extracted_for(url)


@dataclass
class FakeSummarizeFn:
    out: SummaryOutput = field(
        default_factory=lambda: SummaryOutput(
            digest_markdown="## 요약\n트렌드 1",
            model="gemini-2.5-flash",
            article_count=0,
        )
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self, articles: list[SummaryInput], *, api_key: str, model: str
    ) -> SummaryOutput:
        self.calls.append({"n": len(articles), "model": model})
        return SummaryOutput(
            digest_markdown=self.out.digest_markdown,
            model=model,
            article_count=len(articles),
        )


@dataclass
class FakeSendMailFn:
    accepted: list[str] = field(default_factory=lambda: ["x@x.com"])
    refused: dict[str, str] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self,
        *,
        subject: str,
        markdown_body: str,
        sender: str,
        recipients: list[str],
        smtp_password: str,
    ) -> MailSendResult:
        self.calls.append({
            "subject": subject,
            "markdown_body": markdown_body,
            "sender": sender,
            "recipients": list(recipients),
        })
        return MailSendResult(accepted=list(self.accepted), refused=dict(self.refused))


def _make_deps(**overrides: Any) -> tuple[PipelineDeps, dict[str, Any]]:
    store = overrides.pop("store", InMemoryArticleStore())
    fakes: dict[str, Any] = {
        "search_fn": overrides.pop("search_fn", FakeSearchFn()),
        "extract_fn": overrides.pop("extract_fn", FakeExtractFn()),
        "summarize_fn": overrides.pop("summarize_fn", FakeSummarizeFn()),
        "send_mail_fn": overrides.pop("send_mail_fn", FakeSendMailFn()),
    }
    deps = PipelineDeps(store=store, now_fn=_now, **fakes)
    fakes["store"] = store
    return deps, fakes


# ────────── happy path ──────────


def test_run_happy_path_end_to_end() -> None:
    search_fn = FakeSearchFn(by_keyword={
        "kw1": [_result_factory("https://a.com/1", "kw1")],
        "kw2": [_result_factory("https://a.com/2", "kw2")],
    })
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(keywords=["kw1", "kw2"]), deps)

    assert isinstance(result, PipelineResult)
    assert result.status == "success"
    assert result.search_total == 2
    assert result.new_count == 2
    assert result.extracted_count == 2
    assert result.article_count == 2
    assert result.accepted == ["x@x.com"]
    assert result.refused == {}
    assert "트렌드" in result.digest_markdown

    # store now has 2 articles
    store = fakes["store"]
    assert len(store.articles) == 2

    # mail subject formatted with date
    sent = fakes["send_mail_fn"].calls
    assert len(sent) == 1
    assert "2026-05-23" in sent[0]["subject"]


# ────────── dedup ──────────


def test_run_dedups_same_url_across_keywords() -> None:
    search_fn = FakeSearchFn(by_keyword={
        "kw1": [_result_factory("https://a.com/same", "kw1")],
        "kw2": [_result_factory("https://a.com/same", "kw2")],
    })
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(keywords=["kw1", "kw2"]), deps)
    assert result.search_total == 1
    assert result.new_count == 1
    assert result.extracted_count == 1
    assert len(fakes["extract_fn"].calls) == 1


def test_run_skips_urls_already_in_store() -> None:
    store = InMemoryArticleStore()
    store.upsert_article(_extracted_for("https://a.com/known"), keyword="prev", run_id="prev-run")

    search_fn = FakeSearchFn(by_keyword={
        "kw1": [
            _result_factory("https://a.com/known", "kw1"),
            _result_factory("https://a.com/new", "kw1"),
        ],
    })
    deps, _ = _make_deps(search_fn=search_fn, store=store)
    result = run(_params(), deps)
    assert result.search_total == 2
    assert result.new_count == 1  # only the unseen one
    assert result.extracted_count == 1


# ────────── extract failures ──────────


def test_run_skips_extraction_errors_but_keeps_others() -> None:
    urls = [f"https://a.com/{i}" for i in range(3)]
    search_fn = FakeSearchFn(by_keyword={
        "kw1": [_result_factory(u, "kw1") for u in urls],
    })
    extract_fn = FakeExtractFn(raise_on={urls[1]})
    deps, _ = _make_deps(search_fn=search_fn, extract_fn=extract_fn)
    result = run(_params(), deps)
    assert result.search_total == 3
    assert result.new_count == 3
    assert result.extracted_count == 2


def test_run_skips_unexpected_extract_crash() -> None:
    urls = ["https://a.com/1", "https://a.com/2"]
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory(u, "kw1") for u in urls]})
    extract_fn = FakeExtractFn(crash_on={urls[0]})
    deps, _ = _make_deps(search_fn=search_fn, extract_fn=extract_fn)
    result = run(_params(), deps)
    assert result.extracted_count == 1


def test_run_returns_skipped_when_no_articles_extracted() -> None:
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/x", "kw1")]})
    extract_fn = FakeExtractFn(raise_on={"https://a.com/x"})
    deps, fakes = _make_deps(search_fn=search_fn, extract_fn=extract_fn)
    result = run(_params(), deps)
    assert result.status == "skipped"
    assert result.skipped_reason == "no_articles_extracted"
    assert result.digest_markdown == ""
    assert fakes["summarize_fn"].calls == []  # summarize never called
    assert fakes["send_mail_fn"].calls == []


# ────────── search failures ──────────


def test_run_continues_after_search_failure_for_one_keyword() -> None:
    search_fn = FakeSearchFn(
        by_keyword={
            "kw1": [_result_factory("https://a.com/1", "kw1")],
            "kw2": [_result_factory("https://a.com/2", "kw2")],
        },
        raise_on={"kw1"},
    )
    deps, _ = _make_deps(search_fn=search_fn)
    result = run(_params(keywords=["kw1", "kw2"]), deps)
    assert result.status == "success"
    assert result.search_total == 1
    assert result.extracted_count == 1


# ────────── dry_run ──────────


def test_run_dry_run_skips_mail_but_still_summarizes() -> None:
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/1", "kw1")]})
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(dry_run=True), deps)

    assert result.status == "skipped"
    assert result.skipped_reason == "dry_run"
    assert result.article_count == 1
    assert "트렌드" in result.digest_markdown
    assert fakes["send_mail_fn"].calls == []  # mail must NOT be sent
    assert len(fakes["summarize_fn"].calls) == 1


# ────────── cap ──────────


def test_run_caps_summary_input_at_max_articles() -> None:
    urls = [f"https://a.com/{i}" for i in range(25)]
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory(u, "kw1") for u in urls]})
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(max_articles_for_summary=20), deps)
    assert result.extracted_count == 25
    assert result.article_count == 20  # capped
    assert fakes["summarize_fn"].calls[0]["n"] == 20


# ────────── mail refused ──────────


def test_run_records_refused_recipients() -> None:
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/1", "kw1")]})
    send_mail_fn = FakeSendMailFn(accepted=["good@x.com"], refused={"bad@x.com": "550 unknown"})
    deps, _ = _make_deps(search_fn=search_fn, send_mail_fn=send_mail_fn)
    result = run(_params(subscribers=["good@x.com", "bad@x.com"]), deps)
    assert result.status == "success"
    assert result.accepted == ["good@x.com"]
    assert result.refused == {"bad@x.com": "550 unknown"}
