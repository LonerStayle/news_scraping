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
        "source_entries": ["a.com"],  # str list — search 가 host-only entries 로 자동 변환
        "subscribers": ["x@x.com"],
        "brave_search_api_key": "BSK",
        "gemini_api_key": "G",
        "gemini_model": "gemini-2.5-flash",
        "gmail_user": "me@gmail.com",
        "gmail_password": "P",
        "dry_run": False,
        # 테스트 기본은 매체별 cap 비활성 — 단일 매체 결과 다수가 통과해야 하는 기존
        # 시나리오 보존. per-source cap 자체 동작은 별도 테스트에서 검증.
        "max_per_source": 0,
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
        source_entries: list[Any],
        *,
        api_key: str,
        num: int = 10,
        freshness: str = "pd",
    ) -> list[SearchResult]:
        self.calls.append({
            "keyword": keyword,
            "source_entries": source_entries,
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
    # dry_run 시 article 도 store 에 저장하지 않음 (T2)
    assert fakes["store"].articles == {}


# ────────── cap ──────────


def test_run_caps_summary_input_at_max_articles() -> None:
    urls = [f"https://a.com/{i}" for i in range(25)]
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory(u, "kw1") for u in urls]})
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(max_articles_for_summary=20), deps)
    assert result.extracted_count == 25
    assert result.article_count == 20  # capped
    assert fakes["summarize_fn"].calls[0]["n"] == 20


def test_run_caps_per_source_when_one_domain_dominates() -> None:
    """매체 편향 사고 재현 + 해결 검증 — a.com 25개, b.com 25개 결과 시
    max_per_source=3 가 각 매체 3건씩만 통과 (합 6).
    """
    urls_a = [_result_factory(f"https://a.com/{i}", "kw1", domain="a.com") for i in range(25)]
    urls_b = [_result_factory(f"https://b.com/{i}", "kw1", domain="b.com") for i in range(25)]
    search_fn = FakeSearchFn(by_keyword={"kw1": urls_a + urls_b})
    # 본문 추출 결과의 source_domain 까지 매체별로 명시해야 매체 cap 검증 의미 있음.
    by_url = {
        f"https://a.com/{i}": _extracted_for(f"https://a.com/{i}", domain="a.com")
        for i in range(25)
    }
    by_url.update({
        f"https://b.com/{i}": _extracted_for(f"https://b.com/{i}", domain="b.com")
        for i in range(25)
    })
    extract_fn = FakeExtractFn(by_url=by_url)
    deps, fakes = _make_deps(search_fn=search_fn, extract_fn=extract_fn)
    result = run(_params(max_articles_for_summary=20, max_per_source=3), deps)
    assert result.extracted_count == 50  # 모두 추출 단계 통과
    assert result.article_count == 6  # 매체당 3건 × 2 매체
    assert fakes["summarize_fn"].calls[0]["n"] == 6


def test_run_per_source_cap_zero_disables() -> None:
    """max_per_source=0 면 cap 비활성 (단일 매체 결과 모두 통과)."""
    urls = [f"https://a.com/{i}" for i in range(10)]
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory(u, "kw1") for u in urls]})
    deps, fakes = _make_deps(search_fn=search_fn)
    result = run(_params(max_articles_for_summary=20, max_per_source=0), deps)
    assert result.article_count == 10  # cap 없이 다 통과


# ────────── mail refused ──────────


# ────────── G3: RunStore wiring ──────────


def test_run_records_to_run_store_on_success() -> None:
    from ai_news_scraping.run_store import InMemoryRunStore

    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/1", "kw1")]})
    rs = InMemoryRunStore()
    deps, _ = _make_deps(search_fn=search_fn)
    deps.run_store = rs
    result = run(_params(), deps)

    assert result.status == "success"
    recent = rs.list_recent()
    assert len(recent) == 1
    rec = recent[0]
    assert rec.run_id == result.run_id  # pipeline 이 run_store 의 id 사용
    assert rec.status == "success"
    assert rec.article_count == 1
    assert rec.digest_text is not None


def test_run_records_skipped_when_no_articles() -> None:
    from ai_news_scraping.run_store import InMemoryRunStore

    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/x", "kw1")]})
    extract_fn = FakeExtractFn(raise_on={"https://a.com/x"})
    rs = InMemoryRunStore()
    deps, _ = _make_deps(search_fn=search_fn, extract_fn=extract_fn)
    deps.run_store = rs
    result = run(_params(), deps)

    assert result.status == "skipped"
    rec = rs.list_recent()[0]
    assert rec.status == "skipped"
    assert rec.article_count == 0


def test_run_records_failed_on_exception() -> None:
    from ai_news_scraping.run_store import InMemoryRunStore

    rs = InMemoryRunStore()
    # pipeline.py 의 search 는 keyword 별로 try/except 가 있어서 crash 안 함.
    # 더 명확한 시나리오: summarize_fn 이 던지면 _run_inner 가 던지고 run() 이 catch.
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/1", "kw1")]})

    class BrokenSummarize:
        def __call__(self, *args: Any, **kw: Any) -> Any:
            raise RuntimeError("gemini down")

    deps, _ = _make_deps(search_fn=search_fn, summarize_fn=BrokenSummarize())
    deps.run_store = rs

    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="gemini down"):
        run(_params(), deps)

    rec = rs.list_recent()[0]
    assert rec.status == "failed"
    assert rec.error is not None and "gemini" in rec.error


def test_run_records_refused_recipients() -> None:
    search_fn = FakeSearchFn(by_keyword={"kw1": [_result_factory("https://a.com/1", "kw1")]})
    send_mail_fn = FakeSendMailFn(accepted=["good@x.com"], refused={"bad@x.com": "550 unknown"})
    deps, _ = _make_deps(search_fn=search_fn, send_mail_fn=send_mail_fn)
    result = run(_params(subscribers=["good@x.com", "bad@x.com"]), deps)
    assert result.status == "success"
    assert result.accepted == ["good@x.com"]
    assert result.refused == {"bad@x.com": "550 unknown"}
