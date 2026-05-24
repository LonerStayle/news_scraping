"""admin-send-schedule 피처의 AC-1..7 end-to-end 검증.

PRD §5 (admin-send-schedule-requirements.md) 의 7 수용 기준을 1:1 매핑.
빠른 회귀 게이트로 활용.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_news_scraping import cli
from ai_news_scraping.admin import create_app
from ai_news_scraping.config import Settings
from ai_news_scraping.domain_config import DomainConfig, Source
from ai_news_scraping.pipeline import PipelineDeps, PipelineParams, PipelineResult
from ai_news_scraping.run_store import InMemoryRunStore
from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
from ai_news_scraping.search_config_store import (
    InMemoryKeywordStore,
    InMemorySettingsStore,
    InMemorySourceStore,
    SearchSettings,
)
from ai_news_scraping.store import InMemoryArticleStore
from ai_news_scraping.subscriber_store import InMemorySubscriberStore

# ─────────── 공통 fixture ───────────


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "brave_search_api_key": "BSK",
        "gemini_api_key": "G",
        "gemini_model": "gemini-2.5-flash",
        "gmail_user": "me@gmail.com",
        "gmail_app_password": "P",
        "supabase_url": "https://x.supabase.co",
        "supabase_service_role_key": "SRK",
        "admin_token": "TOK",
        "dry_run": False,
        "digest_tz": "Asia/Seoul",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


def _make_domain() -> DomainConfig:
    return DomainConfig(
        keywords=["kw1"],
        sources=[Source(domain="a.com", name="A")],
    )


def _ok_result() -> PipelineResult:
    now = datetime(2026, 5, 24, 0, 40, tzinfo=UTC)
    return PipelineResult(
        run_id="rid",
        started_at=now,
        finished_at=now,
        search_total=1,
        new_count=1,
        extracted_count=1,
        article_count=1,
        digest_markdown="## summary",
        accepted=["x@x.com"],
        refused={},
        status="success",
    )


def _setup_cli_stores(send_hour: int = 9, send_minute: int = 15):
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=True)
    kw = InMemoryKeywordStore()
    src = InMemorySourceStore()
    settings_store = InMemorySettingsStore()
    settings_store.update(send_hour=send_hour, send_minute=send_minute)
    return sub_store, scrape_store, kw, src, settings_store


# ─────────── AC-1 ───────────


def test_AC1_at_target_time_pipeline_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: send=(9,15) 저장 후 9:15 KST trigger → 파이프라인 진행 + runs success."""
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 9, 15, tzinfo=cli.KST),
    )
    sub, scr, kw, src, settings = _setup_cli_stores(9, 15)
    run_store = InMemoryRunStore()
    called: list[str] = []

    def runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub, scrape_store=scr, keyword_store=kw,
        source_store=src, settings_store=settings, run_store=run_store,
        dry_run=False, pipeline_runner=runner,
    )
    assert rc == 0
    assert called == ["ran"]


# ─────────── AC-2 ───────────


def test_AC2_outside_window_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-2: send=(9,15), now=9:00 → 윈도우 (9:10~9:20) 밖, skip, runs 추가 X."""
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 9, 0, tzinfo=cli.KST),
    )
    sub, scr, kw, src, settings = _setup_cli_stores(9, 15)
    run_store = InMemoryRunStore()
    called: list[str] = []

    def runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub, scrape_store=scr, keyword_store=kw,
        source_store=src, settings_store=settings, run_store=run_store,
        dry_run=False, pipeline_runner=runner,
    )
    assert called == []
    assert run_store.list_recent() == []


# ─────────── AC-3 ───────────


def test_AC3_already_sent_today_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3: send=(9,15), now=9:15, 같은 KST 일자 success 존재 → skip."""
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 9, 15, tzinfo=cli.KST),
    )
    sub, scr, kw, src, settings = _setup_cli_stores(9, 15)
    # 같은 날 (KST) 09:00 success 미리 박음
    run_store = InMemoryRunStore(
        now_fn=lambda: datetime(2026, 5, 24, 0, 0, tzinfo=UTC),  # KST 09:00
    )
    r = run_store.start_run()
    run_store.mark_finished(r.run_id, status="success", article_count=5)
    called: list[str] = []

    def runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub, scrape_store=scr, keyword_store=kw,
        source_store=src, settings_store=settings, run_store=run_store,
        dry_run=False, pipeline_runner=runner,
    )
    assert called == []  # 중복 방지


# ─────────── AC-4 ───────────


def test_AC4_force_bypasses_all_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4: force=True 시 시각 / 중복 게이트 모두 무시."""
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 15, 0, tzinfo=cli.KST),  # 윈도우 밖
    )
    sub, scr, kw, src, settings = _setup_cli_stores(9, 15)
    run_store = InMemoryRunStore()
    called: list[str] = []

    def runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub, scrape_store=scr, keyword_store=kw,
        source_store=src, settings_store=settings, run_store=run_store,
        dry_run=False, force=True, pipeline_runner=runner,
    )
    assert called == ["ran"]


# ─────────── AC-5 ───────────


def test_AC5_dry_run_bypasses_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: dry_run=True 시 시각 게이트 무시 (로컬 테스트 용이성)."""
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 15, 0, tzinfo=cli.KST),  # 윈도우 밖
    )
    sub, scr, kw, src, settings = _setup_cli_stores(9, 15)
    called: list[str] = []

    def runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        assert p.dry_run is True
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub, scrape_store=scr, keyword_store=kw,
        source_store=src, settings_store=settings,
        dry_run=True, pipeline_runner=runner,
    )
    assert called == ["ran"]


# ─────────── AC-6 ───────────


@pytest.fixture
def _admin_client():
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore()
    settings_store = InMemorySettingsStore()
    app = create_app(
        admin_token="TOK",
        subscriber_store=sub_store,
        scrape_state_store=scrape_store,
        settings_store=settings_store,
    )
    client = TestClient(app)
    return client, settings_store


def test_AC6_admin_post_invalid_send_time_returns_400(_admin_client) -> None:
    """AC-6: POST send_hour=24 / send_minute=60 등 invalid 시 400."""
    client, _ = _admin_client
    auth = ("admin", "TOK")
    for h, m in [("24", "0"), ("0", "60"), ("-1", "0"), ("0", "-1")]:
        resp = client.post(
            "/settings", auth=auth,
            data={"send_hour": h, "send_minute": m},
            follow_redirects=False,
        )
        assert resp.status_code == 400, f"send=({h},{m}) should reject"


# ─────────── AC-7 ───────────


def test_AC7_default_send_time_after_migration() -> None:
    """AC-7: SearchSettings 기본값 (8, 40) = 기존 cron 23:40 UTC 와 동일.

    마이그레이션 0004 의 DEFAULT (8, 40) 와 SearchSettings dataclass 기본값
    매칭. admin Settings 진입 시 prefill 확인은 form_has_send_time_inputs
    (test_admin.py) 가 별도 커버.
    """
    s = SearchSettings()
    assert s.send_hour == 8
    assert s.send_minute == 40


# ─────────── 보너스: cli 모듈 상수 ───────────


def test_send_window_minutes_is_5() -> None:
    """SEND_WINDOW_MINUTES = 5 (PRD NFR-2 ±5분 윈도우)."""
    assert cli.SEND_WINDOW_MINUTES == 5


def test_kst_zone_is_asia_seoul() -> None:
    """KST = Asia/Seoul (D6 explicit conversion)."""
    assert cli.KST.key == "Asia/Seoul"
