from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ai_news_scraping import cli


@pytest.fixture(autouse=True)
def _patch_now_kst_to_send_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 cli 테스트가 시각 게이트를 통과하도록 KST 시각을 8:40 으로 고정.

    SearchSettings 기본값 (send_hour=8, send_minute=40) 과 매칭 → 시각 게이트 OK.
    신규 시각 게이트 테스트는 본인 monkeypatch.setattr 으로 override.
    """
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 8, 40, tzinfo=cli.KST),
    )
from ai_news_scraping.config import Settings
from ai_news_scraping.domain_config import DomainConfig, Source
from ai_news_scraping.pipeline import PipelineDeps, PipelineParams, PipelineResult
from ai_news_scraping.run_store import InMemoryRunStore
from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
from ai_news_scraping.search_config_loader import LoadedConfig
from ai_news_scraping.search_config_store import (
    InMemoryKeywordStore,
    InMemorySettingsStore,
    InMemorySourceStore,
    SearchSettings,
)
from ai_news_scraping.store import InMemoryArticleStore
from ai_news_scraping.subscriber_store import InMemorySubscriberStore


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "brave_search_api_key": "BSK",
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


def _make_loaded(
    *,
    keywords: list[str] | None = None,
    domains: list[str] | None = None,
    name_map: dict[str, str] | None = None,
    settings: SearchSettings | None = None,
) -> LoadedConfig:
    from ai_news_scraping.search_config_loader import SourceEntry
    d_list = domains if domains is not None else ["a.com", "b.com"]
    nm = name_map if name_map is not None else {"a.com": "A", "b.com": "B"}
    entries = [SourceEntry(host=d, path_prefix="", name=nm.get(d, d)) for d in d_list]
    return LoadedConfig(
        keywords=keywords if keywords is not None else ["kw1", "kw2"],
        source_entries=entries,
        settings=settings if settings is not None else SearchSettings(),
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


def _make_search_stores() -> tuple[
    InMemoryKeywordStore, InMemorySourceStore, InMemorySettingsStore
]:
    return InMemoryKeywordStore(), InMemorySourceStore(), InMemorySettingsStore()


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


def test_build_params_maps_fields_from_loaded_config() -> None:
    params = cli.build_params(
        settings=_make_settings(),
        loaded=_make_loaded(),
        subscribers=["x@x.com", "y@x.com"],
        dry_run=True,
    )
    assert params.keywords == ["kw1", "kw2"]
    assert [e.host for e in params.source_entries] == ["a.com", "b.com"]
    assert params.source_name_map == {"a.com": "A", "b.com": "B"}
    assert params.subscribers == ["x@x.com", "y@x.com"]
    assert params.brave_search_api_key == "BSK"
    assert params.gemini_model == "gemini-2.5-flash"
    assert params.gmail_password == "P"
    assert params.dry_run is True


def test_build_params_uses_settings_overrides() -> None:
    params = cli.build_params(
        settings=_make_settings(),
        loaded=_make_loaded(
            settings=SearchSettings(
                freshness="pm",
                num_results_per_keyword=15,
                max_articles_for_summary=30,
                min_body_len=400,
            )
        ),
        subscribers=["x@x.com"],
        dry_run=False,
    )
    assert params.freshness == "pm"
    assert params.num_results_per_keyword == 15
    assert params.max_articles_for_summary == 30


# ────────── seed_search_config ──────────


def test_seed_imports_yaml_when_db_empty() -> None:
    kw, src, _ = _make_search_stores()
    cli.seed_search_config(kw, src, _make_domain())
    assert kw.list_active() == ["kw1", "kw2"]
    assert [r.domain for r in src.list_active()] == ["a.com", "b.com"]


def test_seed_idempotent_when_db_not_empty() -> None:
    kw, src, _ = _make_search_stores()
    kw.add("existing")
    src.add("existing.com", "Existing")
    cli.seed_search_config(kw, src, _make_domain())
    # yaml seed 가 추가되지 않음 — 기존 그대로
    assert kw.list_active() == ["existing"]
    assert [r.domain for r in src.list_active()] == ["existing.com"]


# ────────── run_command ──────────


def test_run_command_happy_path() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=True)
    article_store = InMemoryArticleStore()
    kw, src, settings = _make_search_stores()
    kw.bulk_seed(["db-kw"])
    src.add("db.com", "DB")
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert captured["params"].keywords == ["db-kw"]  # DB 우선
    assert [e.host for e in captured["params"].source_entries] == ["db.com"]
    assert captured["deps"].store is article_store


def test_run_command_uses_yaml_fallback_when_db_empty() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    kw, src, settings = _make_search_stores()
    captured: dict[str, Any] = {}

    def fake_runner(params: PipelineParams, deps: PipelineDeps) -> PipelineResult:
        captured["params"] = params
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert captured["params"].keywords == ["kw1", "kw2"]
    assert [e.host for e in captured["params"].source_entries] == ["a.com", "b.com"]


def test_run_command_skips_when_scrape_disabled() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=False)
    kw, src, settings = _make_search_stores()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == []


def test_run_command_dry_run_bypasses_scrape_gate() -> None:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=False)
    kw, src, settings = _make_search_stores()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=True,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]


def test_run_command_skips_when_no_subscribers_and_not_dry_run() -> None:
    sub_store = InMemorySubscriberStore()
    kw, src, settings = _make_search_stores()
    called: list[str] = []

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        called.append("ran")
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == []


def test_run_command_failed_status_returns_1() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    kw, src, settings = _make_search_stores()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 1


# ────────── G4: force 모드 ──────────


def test_force_deletes_articles_from_last_success_run() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    article_store = InMemoryArticleStore()
    kw, src, st_settings = _make_search_stores()
    rs = InMemoryRunStore()

    # 직전 success run 시뮬레이션
    prev = rs.start_run()
    rs.mark_finished(prev.run_id, status="success", article_count=2)
    # 그 run 의 article 2개를 store 에 저장
    from ai_news_scraping.extract import ExtractedArticle
    for i in range(2):
        art = ExtractedArticle(
            url=f"https://a.com/{i}", title=f"T{i}", body_text="b" * 400,
            raw_html_excerpt="", published_at=None, source_domain="a.com",
        )
        article_store.upsert_article(art, keyword="kw1", run_id=prev.run_id)
    assert len(article_store.articles) == 2

    captured: dict[str, Any] = {}

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        captured["articles_at_run"] = len(article_store.articles)
        return _ok_result()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=article_store,
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw, source_store=src, settings_store=st_settings,
        run_store=rs,
        dry_run=False,
        force=True,
        pipeline_runner=fake_runner,
    )
    # pipeline 호출 시점에는 이미 직전 run article 2개 삭제됨
    assert captured["articles_at_run"] == 0


def test_force_without_previous_success_is_noop() -> None:
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    rs = InMemoryRunStore()  # 비어 있음
    kw, src, st_settings = _make_search_stores()

    def fake_runner(p: PipelineParams, d: PipelineDeps) -> PipelineResult:
        return _ok_result()

    rc = cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw, source_store=src, settings_store=st_settings,
        run_store=rs,
        dry_run=False,
        force=True,
        pipeline_runner=fake_runner,
    )
    assert rc == 0  # 그냥 진행


def test_force_false_does_not_delete() -> None:
    article_store = InMemoryArticleStore()
    rs = InMemoryRunStore()
    prev = rs.start_run()
    rs.mark_finished(prev.run_id, status="success", article_count=1)
    from ai_news_scraping.extract import ExtractedArticle
    article_store.upsert_article(
        ExtractedArticle(
            url="https://a.com/x", title="T", body_text="b" * 400,
            raw_html_excerpt="", published_at=None, source_domain="a.com",
        ),
        keyword="kw1", run_id=prev.run_id,
    )

    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    kw, src, st_settings = _make_search_stores()

    cli.run_command(
        settings=_make_settings(),
        domain_cfg=_make_domain(),
        article_store=article_store,
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw, source_store=src, settings_store=st_settings,
        run_store=rs,
        dry_run=False,
        force=False,  # default
        pipeline_runner=lambda p, d: _ok_result(),
    )
    # 삭제 안 됨
    assert len(article_store.articles) == 1


def test_run_command_settings_dry_run_flag_overrides_cli() -> None:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=False)
    kw, src, settings = _make_search_stores()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert seen["dry_run"] is True


# ────────── 시각 게이트 (send-schedule) ──────────


def _make_send_window_setup(send_hour: int = 8, send_minute: int = 40):
    """공통 setup — subscribers + scrape ON + settings 의 send_hour/send_minute."""
    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")
    scrape_store = InMemoryScrapeStateStore(initial=True)
    kw, src, settings = _make_search_stores()
    settings.update(send_hour=send_hour, send_minute=send_minute)
    return sub_store, scrape_store, kw, src, settings


def test_send_schedule_outside_window_skips_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=9:00 (윈도우 8:35~8:45 밖) → skip
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 9, 0, tzinfo=cli.KST),
    )
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
    run_store = InMemoryRunStore()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        run_store=run_store,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == []  # pipeline 호출 X
    # runs 추가 X — start_run 안 호출
    assert run_store.list_recent() == []


def test_send_schedule_inside_window_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=8:42 (윈도우 안) → 진행
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 8, 42, tzinfo=cli.KST),
    )
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
    run_store = InMemoryRunStore()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        run_store=run_store,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]


def test_send_schedule_already_sent_today_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=8:40 (윈도우 안) + 오늘 success 존재 → skip
    fixed_now = datetime(2026, 5, 24, 8, 40, tzinfo=cli.KST)
    monkeypatch.setattr(cli, "_now_kst", lambda: fixed_now)
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
    # 오늘 success run 미리 박아둠 (finished_at = 같은 KST 일자 안)
    run_store = InMemoryRunStore(
        now_fn=lambda: datetime(2026, 5, 24, 0, 30, tzinfo=UTC),  # 09:30 KST
    )
    r = run_store.start_run()
    run_store.mark_finished(r.run_id, status="success", article_count=5)

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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        run_store=run_store,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == []  # 중복 발송 차단


def test_send_schedule_force_bypasses_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=15:00 (윈도우 밖), force=True → 진행
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 15, 0, tzinfo=cli.KST),
    )
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
    run_store = InMemoryRunStore()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        run_store=run_store,
        dry_run=False,
        force=True,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]  # force=True → 시각 무관 진행


def test_send_schedule_dry_run_bypasses_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=15:00 (윈도우 밖), dry_run=True → 진행
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 15, 0, tzinfo=cli.KST),
    )
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        dry_run=True,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]


def test_send_schedule_window_boundary_exact_5min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # send=8:40, now=8:45 (정확히 5분 차이, 윈도우 안) → 진행
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 8, 45, tzinfo=cli.KST),
    )
    sub_store, scrape_store, kw, src, settings = _make_send_window_setup()
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
        keyword_store=kw,
        source_store=src,
        settings_store=settings,
        run_store=InMemoryRunStore(),
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0
    assert called == ["ran"]
