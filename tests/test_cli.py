from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ai_news_scraping import cli
from ai_news_scraping.config import Settings
from ai_news_scraping.domain_config import DomainConfig, Source
from ai_news_scraping.pipeline import PipelineDeps, PipelineParams, PipelineResult
from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
from ai_news_scraping.store import InMemoryArticleStore
from ai_news_scraping.subscriber_store import InMemorySubscriberStore


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "google_cse_api_key": "K",
        "google_cse_cx": "CX",
        "gemini_api_key": "G",
        "gemini_model": "gemini-2.5-flash",
        "gmail_user": "me@gmail.com",
        "gmail_app_password": "P",
        "supabase_url": "https://x.supabase.co",
        "supabase_service_role_key": "SRK",
        "admin_token": "T",
        "dry_run": False,
        "digest_tz": "Asia/Seoul",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


def _make_domain() -> DomainConfig:
    return DomainConfig(
        keywords=["kw1", "kw2"],
        sources=[Source(domain="a.com", name="A"), Source(domain="b.com", name="B")],
    )


def _ok_result() -> PipelineResult:
    now = datetime(2026, 5, 23, 0, 40, 0, tzinfo=UTC)
    return PipelineResult(
        run_id="rid",
        started_at=now,
        finished_at=now,
        search_total=2,
        new_count=2,
        extracted_count=2,
        article_count=2,
        digest_markdown="## summary",
        accepted=["x@x.com"],
        refused={},
        status="success",
    )


# ────────── _parse_args ──────────


def test_parse_args_run_with_dry_run() -> None:
    args = cli._parse_args(["run", "--dry-run"])
    assert args.cmd == "run"
    assert args.dry_run is True
    assert args.domain == "ai_news"


def test_parse_args_run_with_custom_domain() -> None:
    args = cli._parse_args(["run", "--domain", "other_topic"])
    assert args.domain == "other_topic"
    assert args.dry_run is False


def test_parse_args_missing_command() -> None:
    with pytest.raises(SystemExit):
        cli._parse_args([])


# ────────── build_params ──────────


def test_build_params_maps_fields() -> None:
    params = cli.build_params(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        subscribers=["x@x.com", "y@x.com"],
        dry_run=True,
    )
    assert params.keywords == ["kw1", "kw2"]
    assert params.source_domains == ["a.com", "b.com"]
    assert params.subscribers == ["x@x.com", "y@x.com"]
    assert params.google_cse_api_key == "K"
    assert params.gemini_model == "gemini-2.5-flash"
    assert params.gmail_password == "P"
    assert params.dry_run is True


# ────────── run_command ──────────


def test_run_command_happy_path() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=True)
    article_store = InMemoryArticleStore()
    captured: dict[str, Any] = {}

    def fake_runner(params: PipelineParams, deps: PipelineDeps) -> PipelineResult:
        captured["params"] = params
        captured["deps"] = deps
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=article_store,
        sub_store=sub_store,
        scrape_store=scrape_store,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert captured["params"].subscribers == ["x@x.com"]
    assert captured["params"].dry_run is False
    assert captured["deps"].store is article_store


def test_run_command_skips_when_scrape_disabled() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=False)
    called: list[str] = []

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=scrape_store,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == []  # pipeline never invoked


def test_run_command_dry_run_bypasses_scrape_gate() -> None:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=False)  # OFF
    called: list[str] = []

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        assert p.dry_run is True
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=scrape_store,
        dry_run=True,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]


def test_run_command_skips_when_no_subscribers_and_not_dry_run() -> None:
    sub_store = InMemorySubscriberStore()  # empty
    scrape_store = InMemoryScrapeStateStore(initial=True)
    called: list[str] = []

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=scrape_store,
        dry_run=False,
        pipeline_runner=lambda p, d: called.append("ran") or _ok_result(),  # type: ignore[func-returns-value]
    )
    assert rc == 0
    assert called == []


def test_run_command_failed_status_returns_1() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    now = datetime(2026, 5, 23, 0, 40, 0, tzinfo=UTC)

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        return PipelineResult(
            run_id="r",
            started_at=now,
            finished_at=now,
            search_total=0,
            new_count=0,
            extracted_count=0,
            article_count=0,
            digest_markdown="",
            accepted=[],
            refused={},
            status="failed",
        )

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 1


def test_run_command_settings_dry_run_flag_overrides_cli() -> None:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=False)
    seen: dict[str, Any] = {}

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        seen["dry_run"] = p.dry_run
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(dry_run=True),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=scrape_store,
        dry_run=False,  # CLI flag False, but settings.dry_run=True wins
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert seen["dry_run"] is True
