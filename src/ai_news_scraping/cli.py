"""CLI entry point — ``python -m ai_news_scraping.cli run [--dry-run]``.

GitHub Actions cron 이 호출하는 진입점. 단순 구조:
  1. argparse 로 명령/플래그 파싱
  2. config + domain_config 로드
  3. Supabase 클라이언트 + 3 store 구성
  4. ``run_command`` 가 게이트 (scrape ON/OFF, subscribers 있음) 후 pipeline.run
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Any

from . import pipeline as pipeline_mod
from .config import Settings, get_settings
from .domain_config import DomainConfig, load_domain
from .pipeline import PipelineDeps, PipelineParams, PipelineResult
from .scrape_state_store import ScrapeStateStore, SupabaseScrapeStateStore
from .store import ArticleStore, SupabaseArticleStore
from .subscriber_store import SubscriberStore, SupabaseSubscriberStore

logger = logging.getLogger(__name__)

PipelineRunner = Callable[[PipelineParams, PipelineDeps], PipelineResult]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.cmd == "run":
        return _entry_run(dry_run=bool(args.dry_run), domain=str(args.domain))
    return 2


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_news_scraping")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run the daily digest pipeline")
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="검색·추출·요약까지만 수행하고 메일 발송은 skip",
    )
    run_p.add_argument(
        "--domain",
        default="ai_news",
        help="domains/<name>/ 의 키워드·매체 config 선택 (기본: ai_news)",
    )
    return parser.parse_args(argv)


def _entry_run(*, dry_run: bool, domain: str) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    domain_cfg = load_domain(domain)
    client = _make_supabase_client(settings)
    schema = settings.supabase_schema
    return run_command(
        settings=settings,
        domain_cfg=domain_cfg,
        article_store=SupabaseArticleStore(client, schema=schema),
        sub_store=SupabaseSubscriberStore(client, schema=schema),
        scrape_store=SupabaseScrapeStateStore(client, schema=schema),
        dry_run=dry_run,
    )


def _make_supabase_client(settings: Settings) -> Any:
    # Lazy import — keeps unit tests off the supabase code path.
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def run_command(
    *,
    settings: Settings,
    domain_cfg: DomainConfig,
    article_store: ArticleStore,
    sub_store: SubscriberStore,
    scrape_store: ScrapeStateStore,
    dry_run: bool = False,
    pipeline_runner: PipelineRunner = pipeline_mod.run,
) -> int:
    effective_dry_run = dry_run or settings.dry_run

    if not effective_dry_run and not scrape_store.is_enabled():
        logger.info("scrape_enabled=False, skipping run")
        return 0

    subscribers = sub_store.list_active_emails()
    if not subscribers and not effective_dry_run:
        logger.warning("no active subscribers, skipping mail send")
        return 0

    params = build_params(
        settings=settings,
        domain_cfg=domain_cfg,
        subscribers=subscribers,
        dry_run=effective_dry_run,
    )
    deps = PipelineDeps(store=article_store)
    result = pipeline_runner(params, deps)

    logger.info(
        "run_id=%s status=%s search=%d extracted=%d articles=%d accepted=%d refused=%d",
        result.run_id,
        result.status,
        result.search_total,
        result.extracted_count,
        result.article_count,
        len(result.accepted),
        len(result.refused),
    )
    return 0 if result.status != "failed" else 1


def build_params(
    *,
    settings: Settings,
    domain_cfg: DomainConfig,
    subscribers: list[str],
    dry_run: bool,
) -> PipelineParams:
    return PipelineParams(
        keywords=list(domain_cfg.keywords),
        source_domains=[s.domain for s in domain_cfg.sources],
        subscribers=subscribers,
        brave_search_api_key=settings.brave_search_api_key,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        gmail_user=settings.gmail_user,
        gmail_password=settings.gmail_app_password,
        dry_run=dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
