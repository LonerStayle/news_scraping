"""Daily digest pipeline — Phase B end-to-end orchestration.

흐름 (CLAUDE.md §3):
  1. 키워드 × 매체 화이트리스트 → Google CSE 검색 (키워드당 1 호출)
  2. URL dedup (in-batch + DB existing)
  3. trafilatura 본문 추출 (실패는 skip)
  4. store 에 article upsert (DB 보존)
  5. Gemini 로 한국어 통합 트렌드 요약 (최대 N건)
  6. Gmail SMTP 로 구독자 명단 BCC 일괄 발송 (dry_run 이면 skip)

모든 외부 작용 (search / extract / summarize / send_mail / store / now)
은 ``PipelineDeps`` 로 주입 — fully testable.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import extract as extract_mod
from . import mail as mail_mod
from . import search as search_mod
from . import summarize as summarize_mod
from .extract import ExtractedArticle, ExtractionError
from .search import SearchResult
from .store import ArticleStore
from .summarize import SummaryInput, SummaryOutput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineParams:
    keywords: list[str]
    source_domains: list[str]
    subscribers: list[str]
    brave_search_api_key: str
    gemini_api_key: str
    gemini_model: str
    gmail_user: str
    gmail_password: str
    dry_run: bool = False
    num_results_per_keyword: int = 20  # Brave max — 더 많은 후보 확보
    max_articles_for_summary: int = 20
    freshness: str = "pw"  # Brave Search: past week — pd 보다 풍부
    search_delay_seconds: float = 1.2  # Brave Free: 1 query/sec rate limit
    subject_template: str = "오늘의 AI 트렌드 ({date})"


SearchFn = Callable[..., list[SearchResult]]
ExtractFn = Callable[[str], ExtractedArticle]
SummarizeFn = Callable[..., SummaryOutput]
SendMailFn = Callable[..., mail_mod.MailSendResult]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class PipelineDeps:
    store: ArticleStore
    search_fn: SearchFn = field(default=search_mod.search)
    extract_fn: ExtractFn = field(default=extract_mod.extract)
    summarize_fn: SummarizeFn = field(default=summarize_mod.summarize)
    send_mail_fn: SendMailFn = field(default=mail_mod.send_digest)
    now_fn: Callable[[], datetime] = field(default=_utc_now)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    started_at: datetime
    finished_at: datetime
    search_total: int
    new_count: int
    extracted_count: int
    article_count: int
    digest_markdown: str
    accepted: list[str]
    refused: dict[str, str]
    status: str  # "success" | "skipped" | "failed"
    skipped_reason: str | None = None


def run(params: PipelineParams, deps: PipelineDeps) -> PipelineResult:
    run_id = str(uuid.uuid4())
    started_at = deps.now_fn()

    # ───── 1) 검색 ─────
    raw_results: list[SearchResult] = []
    for i, keyword in enumerate(params.keywords):
        if i > 0 and params.search_delay_seconds > 0:
            # Brave Free tier: 1 query/sec. 키워드 사이 sleep 으로 429 방어.
            time.sleep(params.search_delay_seconds)
        try:
            results = deps.search_fn(
                keyword,
                params.source_domains,
                api_key=params.brave_search_api_key,
                num=params.num_results_per_keyword,
                freshness=params.freshness,
            )
        except Exception as e:
            logger.warning("search failed for keyword=%r: %s", keyword, e)
            continue
        raw_results.extend(results)

    # ───── 2) dedup (in-batch + DB) ─────
    deduped = _dedup_in_batch(raw_results)
    existing = deps.store.existing_urls(r.url for r in deduped)
    new_results = [r for r in deduped if r.url not in existing]

    # ───── 3, 4) 본문 추출 + DB 저장 ─────
    extracted: list[tuple[SearchResult, ExtractedArticle]] = []
    for r in new_results:
        try:
            article = deps.extract_fn(r.url)
        except ExtractionError as e:
            logger.info("extract skipped: %s (%s)", r.url, e)
            continue
        except Exception as e:
            logger.warning("extract crashed: %s (%s)", r.url, e)
            continue
        deps.store.upsert_article(article, keyword=r.keyword, run_id=run_id)
        extracted.append((r, article))

    # ───── 5) Gemini 요약 ─────
    if not extracted:
        return _result(
            run_id, started_at, deps.now_fn(),
            search_total=len(deduped),
            new_count=len(new_results),
            extracted_count=0,
            article_count=0,
            digest_markdown="",
            accepted=[],
            refused={},
            status="skipped",
            skipped_reason="no_articles_extracted",
        )

    capped = extracted[: params.max_articles_for_summary]
    summary_inputs = [
        SummaryInput(
            title=a.title,
            source_domain=a.source_domain,
            url=a.url,
            body_text=a.body_text,
            published_at=a.published_at,
        )
        for _, a in capped
    ]
    summary: SummaryOutput = deps.summarize_fn(
        summary_inputs,
        api_key=params.gemini_api_key,
        model=params.gemini_model,
    )

    # ───── 6) 메일 발송 (dry_run 이면 skip) ─────
    if params.dry_run:
        return _result(
            run_id, started_at, deps.now_fn(),
            search_total=len(deduped),
            new_count=len(new_results),
            extracted_count=len(extracted),
            article_count=summary.article_count,
            digest_markdown=summary.digest_markdown,
            accepted=[],
            refused={},
            status="skipped",
            skipped_reason="dry_run",
        )

    subject = params.subject_template.format(
        date=started_at.strftime("%Y-%m-%d"),
    )
    mail_result = deps.send_mail_fn(
        subject=subject,
        markdown_body=summary.digest_markdown,
        sender=params.gmail_user,
        recipients=params.subscribers,
        smtp_password=params.gmail_password,
    )

    return _result(
        run_id, started_at, deps.now_fn(),
        search_total=len(deduped),
        new_count=len(new_results),
        extracted_count=len(extracted),
        article_count=summary.article_count,
        digest_markdown=summary.digest_markdown,
        accepted=list(mail_result.accepted),
        refused=dict(mail_result.refused),
        status="success",
    )


def _dedup_in_batch(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for r in results:
        if r.url in seen:
            continue
        seen.add(r.url)
        unique.append(r)
    return unique


def _result(
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    *,
    search_total: int,
    new_count: int,
    extracted_count: int,
    article_count: int,
    digest_markdown: str,
    accepted: list[str],
    refused: dict[str, str],
    status: str,
    skipped_reason: str | None = None,
) -> PipelineResult:
    return PipelineResult(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        search_total=search_total,
        new_count=new_count,
        extracted_count=extracted_count,
        article_count=article_count,
        digest_markdown=digest_markdown,
        accepted=accepted,
        refused=refused,
        status=status,
        skipped_reason=skipped_reason,
    )


__all__ = [
    "PipelineDeps",
    "PipelineParams",
    "PipelineResult",
    "run",
]
