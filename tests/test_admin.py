from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_news_scraping.admin import create_app
from ai_news_scraping.run_store import InMemoryRunStore
from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
from ai_news_scraping.search_config_store import (
    InMemoryKeywordStore,
    InMemorySettingsStore,
    InMemorySourceStore,
)
from ai_news_scraping.subscriber_store import InMemorySubscriberStore

ADMIN_TOKEN = "test-token"
AUTH = ("admin", ADMIN_TOKEN)


@dataclass
class AdminCtx:
    client: TestClient
    sub_store: InMemorySubscriberStore
    scrape_store: InMemoryScrapeStateStore
    keyword_store: InMemoryKeywordStore
    source_store: InMemorySourceStore
    settings_store: InMemorySettingsStore


@pytest.fixture
def ctx() -> AdminCtx:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=True)
    keyword_store = InMemoryKeywordStore()
    source_store = InMemorySourceStore()
    settings_store = InMemorySettingsStore()
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=sub_store,
        scrape_state_store=scrape_store,
        keyword_store=keyword_store,
        source_store=source_store,
        settings_store=settings_store,
    )
    return AdminCtx(
        client=TestClient(app),
        sub_store=sub_store,
        scrape_store=scrape_store,
        keyword_store=keyword_store,
        source_store=source_store,
        settings_store=settings_store,
    )


# ────────── Authentication ──────────


def test_unauthenticated_returns_401(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/")
    assert resp.status_code == 401


def test_wrong_token_returns_401(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/", auth=("admin", "wrong"))
    assert resp.status_code == 401


def test_correct_token_returns_html(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "뉴스 스크래핑" in resp.text


# ────────── Scrape toggle ──────────


def test_index_shows_scrape_state(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/", auth=AUTH)
    assert "state-on" in resp.text


def test_toggle_flips_state(ctx: AdminCtx) -> None:
    assert ctx.scrape_store.is_enabled() is True
    resp = ctx.client.post(
        "/scrape-enabled/toggle", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert ctx.scrape_store.is_enabled() is False


def test_toggle_requires_auth(ctx: AdminCtx) -> None:
    resp = ctx.client.post("/scrape-enabled/toggle", follow_redirects=False)
    assert resp.status_code == 401


# ────────── Subscribers ──────────


def test_add_subscriber(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/subscribers",
        auth=AUTH,
        data={"email": "user@example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert ctx.sub_store.list_active_emails() == ["user@example.com"]


def test_add_invalid_email_returns_400(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/subscribers",
        auth=AUTH,
        data={"email": "not-an-email"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "invalid email" in resp.json()["detail"]


def test_add_subscriber_requires_auth(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/subscribers", data={"email": "x@x.com"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_remove_subscriber(ctx: AdminCtx) -> None:
    sub = ctx.sub_store.add("user@example.com")
    resp = ctx.client.post(
        f"/subscribers/{sub.id}/delete", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303
    assert ctx.sub_store.list_all() == []


def test_remove_nonexistent_subscriber_is_idempotent(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/subscribers/999/delete", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303  # store returns False but route still redirects


def test_index_renders_subscriber_list(ctx: AdminCtx) -> None:
    ctx.sub_store.add("a@example.com")
    ctx.sub_store.add("b@example.com")
    resp = ctx.client.get("/", auth=AUTH)
    assert "a@example.com" in resp.text
    assert "b@example.com" in resp.text
    assert "2명" in resp.text


# ────────── Keywords (F5) ──────────


def test_add_keyword(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/keywords", auth=AUTH, data={"keyword": "AI safety"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert ctx.keyword_store.list_active() == ["AI safety"]


def test_add_keyword_invalid_returns_400(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/keywords", auth=AUTH, data={"keyword": "   "},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_add_keyword_requires_auth(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/keywords", data={"keyword": "AI"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_remove_keyword(ctx: AdminCtx) -> None:
    rec = ctx.keyword_store.add("AI")
    resp = ctx.client.post(
        f"/keywords/{rec.id}/delete", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303
    assert ctx.keyword_store.list_all() == []


def test_toggle_keyword_flips_active(ctx: AdminCtx) -> None:
    rec = ctx.keyword_store.add("AI")
    assert rec.active is True
    resp = ctx.client.post(
        f"/keywords/{rec.id}/toggle", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303
    assert ctx.keyword_store.list_all()[0].active is False
    # 다시 토글
    ctx.client.post(
        f"/keywords/{rec.id}/toggle", auth=AUTH, follow_redirects=False
    )
    assert ctx.keyword_store.list_all()[0].active is True


def test_toggle_keyword_unknown_id_returns_404(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/keywords/999/toggle", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 404


def test_index_renders_keywords(ctx: AdminCtx) -> None:
    ctx.keyword_store.add("artificial intelligence")
    ctx.keyword_store.add("LLM")
    resp = ctx.client.get("/", auth=AUTH)
    assert "artificial intelligence" in resp.text
    assert "LLM" in resp.text
    assert "2개" in resp.text


def test_keyword_routes_503_when_store_missing() -> None:
    """keyword_store=None 으로 app 생성 시 라우트가 503 반환 (graceful)."""
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore()
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=sub_store,
        scrape_state_store=scrape_store,
        keyword_store=None,
    )
    client = TestClient(app)
    resp = client.post(
        "/keywords", auth=AUTH, data={"keyword": "AI"}, follow_redirects=False
    )
    assert resp.status_code == 503


# ────────── Sources (F6) ──────────


def test_add_source(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/sources", auth=AUTH,
        data={"domain": "techcrunch.com", "name": "TechCrunch"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    recs = ctx.source_store.list_active()
    assert len(recs) == 1
    assert recs[0].domain == "techcrunch.com"
    assert recs[0].name == "TechCrunch"


def test_add_source_strips_www(ctx: AdminCtx) -> None:
    ctx.client.post(
        "/sources", auth=AUTH,
        data={"domain": "www.theverge.com", "name": "The Verge"},
        follow_redirects=False,
    )
    assert ctx.source_store.list_all()[0].domain == "theverge.com"


def test_add_source_invalid_returns_400(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/sources", auth=AUTH,
        data={"domain": "  ", "name": "X"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_add_source_requires_auth(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/sources", data={"domain": "a.com", "name": "A"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_remove_source(ctx: AdminCtx) -> None:
    rec = ctx.source_store.add("a.com", "A")
    resp = ctx.client.post(
        f"/sources/{rec.id}/delete", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 303
    assert ctx.source_store.list_all() == []


def test_toggle_source_flips_active(ctx: AdminCtx) -> None:
    rec = ctx.source_store.add("a.com", "A")
    ctx.client.post(
        f"/sources/{rec.id}/toggle", auth=AUTH, follow_redirects=False
    )
    assert ctx.source_store.list_all()[0].active is False
    ctx.client.post(
        f"/sources/{rec.id}/toggle", auth=AUTH, follow_redirects=False
    )
    assert ctx.source_store.list_all()[0].active is True


def test_toggle_source_unknown_id_returns_404(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/sources/999/toggle", auth=AUTH, follow_redirects=False
    )
    assert resp.status_code == 404


def test_index_renders_sources(ctx: AdminCtx) -> None:
    ctx.source_store.add("techcrunch.com", "TechCrunch")
    ctx.source_store.add("theverge.com", "The Verge")
    resp = ctx.client.get("/", auth=AUTH)
    assert "techcrunch.com" in resp.text
    assert "TechCrunch" in resp.text
    assert "The Verge" in resp.text
    assert "2개" in resp.text


def test_source_routes_503_when_store_missing() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        keyword_store=None,
        source_store=None,
    )
    client = TestClient(app)
    resp = client.post(
        "/sources", auth=AUTH,
        data={"domain": "a.com", "name": "A"},
        follow_redirects=False,
    )
    assert resp.status_code == 503


# ────────── Settings (F7) ──────────


def test_settings_update_freshness(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/settings", auth=AUTH,
        data={"freshness": "pm"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert ctx.settings_store.get().freshness == "pm"


def test_settings_update_multiple(ctx: AdminCtx) -> None:
    ctx.client.post(
        "/settings", auth=AUTH,
        data={
            "freshness": "pd",
            "num_results_per_keyword": "15",
            "max_articles_for_summary": "30",
            "min_body_len": "400",
        },
        follow_redirects=False,
    )
    cur = ctx.settings_store.get()
    assert cur.freshness == "pd"
    assert cur.num_results_per_keyword == 15
    assert cur.max_articles_for_summary == 30
    assert cur.min_body_len == 400


def test_settings_update_partial_preserves_other_fields(ctx: AdminCtx) -> None:
    ctx.client.post(
        "/settings", auth=AUTH,
        data={"freshness": "pm"},
        follow_redirects=False,
    )
    cur = ctx.settings_store.get()
    assert cur.freshness == "pm"
    assert cur.num_results_per_keyword == 20  # 기본값 유지
    assert cur.max_articles_for_summary == 20
    assert cur.min_body_len == 300


def test_settings_invalid_freshness_returns_400(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/settings", auth=AUTH,
        data={"freshness": "px"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_settings_out_of_range_returns_400(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/settings", auth=AUTH,
        data={"num_results_per_keyword": "50"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_settings_requires_auth(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/settings", data={"freshness": "pd"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_settings_renders_in_index(ctx: AdminCtx) -> None:
    ctx.settings_store.update(freshness="pm")
    resp = ctx.client.get("/", auth=AUTH)
    # 현재 선택된 freshness 가 select 에서 selected 로 표시되어야
    assert "운영 설정" in resp.text
    assert 'value="pm"' in resp.text


def test_settings_update_send_time(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/settings", auth=AUTH,
        data={"send_hour": "9", "send_minute": "15"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cur = ctx.settings_store.get()
    assert cur.send_hour == 9
    assert cur.send_minute == 15
    # 다른 필드 유지
    assert cur.freshness == "pw"


def test_settings_invalid_send_hour_returns_400(ctx: AdminCtx) -> None:
    for bad in ("24", "-1", "99"):
        resp = ctx.client.post(
            "/settings", auth=AUTH,
            data={"send_hour": bad, "send_minute": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 400, f"send_hour={bad} should reject"


def test_settings_invalid_send_minute_returns_400(ctx: AdminCtx) -> None:
    for bad in ("60", "-1", "99"):
        resp = ctx.client.post(
            "/settings", auth=AUTH,
            data={"send_hour": "8", "send_minute": bad},
            follow_redirects=False,
        )
        assert resp.status_code == 400, f"send_minute={bad} should reject"


def test_settings_send_time_partial_preserves_other(ctx: AdminCtx) -> None:
    ctx.client.post(
        "/settings", auth=AUTH,
        data={"send_hour": "10"},
        follow_redirects=False,
    )
    cur = ctx.settings_store.get()
    assert cur.send_hour == 10
    assert cur.send_minute == 40  # 기본값 유지


def test_compute_recommended_small_5x5_returns_pm() -> None:
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    rec = _compute_recommended([_R() for _ in range(5)], [_R() for _ in range(5)])
    assert rec["active_keywords"] == 5
    assert rec["active_sources"] == 5
    assert rec["max_articles_for_summary"] == 35  # max(20, 5*5+10)
    assert rec["freshness"] == "pm"  # 25 < 50
    assert rec["brave_calls_per_day"] == 5


def test_compute_recommended_medium_10x10_returns_pw() -> None:
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    rec = _compute_recommended([_R() for _ in range(10)], [_R() for _ in range(10)])
    assert rec["max_articles_for_summary"] == 60  # 10*5+10
    assert rec["freshness"] == "pw"  # 100 >= 50, <200


def test_compute_recommended_user_scenario_14x14() -> None:
    """대표님 시나리오 — 키워드 14 + 소스 14."""
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    rec = _compute_recommended([_R() for _ in range(14)], [_R() for _ in range(14)])
    assert rec["active_keywords"] == 14
    assert rec["max_articles_for_summary"] == 80  # 14*5+10
    assert rec["freshness"] == "pw"  # 196 < 200
    assert rec["brave_calls_per_month"] == 420
    # cap 분산 강제: 80 / 14 / 2 = 2.86 → round 3
    # (이전 공식 ×1.5 는 9 라 cap 무력 — 한 매체 우위 사고 재발)
    assert rec["max_per_source"] == 3


def test_compute_recommended_max_per_source_bounded() -> None:
    """max_per_source 권장값은 2~5 범위로 clamp."""
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    # 매체 1개만 active 면 max_articles / 1 / 2 = 큰 값 → 5 로 clamp
    rec_few = _compute_recommended([_R() for _ in range(5)], [_R()])
    assert rec_few["max_per_source"] == 5
    # 매체 30개 active 면 max_articles / 30 / 2 ≈ 1.33 → 1.0 round = 1 → max(2,1) = 2
    rec_many = _compute_recommended([_R() for _ in range(5)], [_R() for _ in range(30)])
    assert rec_many["max_per_source"] == 2


def test_compute_recommended_large_15x15_returns_pd() -> None:
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    rec = _compute_recommended([_R() for _ in range(15)], [_R() for _ in range(15)])
    assert rec["freshness"] == "pd"  # 225 >= 200


def test_compute_recommended_excludes_inactive() -> None:
    from dataclasses import dataclass

    from ai_news_scraping.admin import _compute_recommended

    @dataclass
    class _R:
        active: bool = True

    kws = [_R(active=True), _R(active=False), _R(active=True)]
    srcs = [_R(active=True)]
    rec = _compute_recommended(kws, srcs)
    assert rec["active_keywords"] == 2  # active 만 카운트
    assert rec["active_sources"] == 1


def test_index_shows_recommended_card(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    assert "스마트 권장값" in resp.text


def test_overview_shows_send_time(ctx: AdminCtx) -> None:
    ctx.settings_store.update(send_hour=9, send_minute=15)
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    # Overview 카드의 "발송 시각" 라인에 "09:15 KST" 표시
    assert "발송 시각" in resp.text
    assert "09:15 KST" in resp.text


def test_settings_form_has_send_time_inputs(ctx: AdminCtx) -> None:
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    # Settings 폼의 send_hour / send_minute input 존재
    assert 'name="send_hour"' in resp.text
    assert 'name="send_minute"' in resp.text


def test_settings_route_503_when_store_missing() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        settings_store=None,
    )
    client = TestClient(app)
    resp = client.post(
        "/settings", auth=AUTH, data={"freshness": "pd"}, follow_redirects=False
    )
    assert resp.status_code == 503


# ────────── /run-now (G5) ──────────


def test_run_now_invokes_pipeline_callback_with_dry_run_and_force() -> None:
    calls: list[tuple[bool, bool]] = []

    def fake_pipeline(dry_run: bool, force: bool) -> None:
        calls.append((dry_run, force))

    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_pipeline=fake_pipeline,
    )
    client = TestClient(app)
    resp = client.post(
        "/run-now", auth=AUTH,
        data={"dry_run": "true", "force": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "triggered=dry-force" in resp.headers["location"]
    # BackgroundTasks 는 TestClient 가 응답 후 즉시 실행 → 1회 호출됨
    assert calls == [(True, True)]


def test_run_now_default_is_force_live() -> None:
    calls: list[tuple[bool, bool]] = []

    def fake_pipeline(dry_run: bool, force: bool) -> None:
        calls.append((dry_run, force))

    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_pipeline=fake_pipeline,
    )
    client = TestClient(app)
    # 폼 안 보내면 기본값 사용 (dry_run=False, force=True)
    resp = client.post("/run-now", auth=AUTH, data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert "triggered=force" in resp.headers["location"]
    assert calls == [(False, True)]


def test_run_now_503_when_callback_not_configured() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_pipeline=None,
    )
    client = TestClient(app)
    resp = client.post("/run-now", auth=AUTH, data={}, follow_redirects=False)
    assert resp.status_code == 503


def test_run_now_requires_auth() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_pipeline=lambda dr, f: None,
    )
    client = TestClient(app)
    resp = client.post("/run-now", data={}, follow_redirects=False)
    assert resp.status_code == 401


# ────────── History 탭 (G7) ──────────


def test_history_tab_lists_recent_runs() -> None:
    rs = InMemoryRunStore()
    r1 = rs.start_run()
    rs.mark_finished(
        r1.run_id, status="success", article_count=12,
        digest_text="오늘의 AI 트렌드 요약",
    )
    r2 = rs.start_run()
    rs.mark_finished(r2.run_id, status="failed", article_count=0, error="brave 500")

    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_store=rs,
    )
    client = TestClient(app)
    resp = client.get("/", auth=AUTH)
    text = resp.text
    # 두 run 모두 표시
    assert r1.run_id[:8] in text
    assert r2.run_id[:8] in text
    # 상태 표시
    assert "success" in text
    assert "failed" in text
    # 에러 메시지 일부 표시
    assert "brave 500" in text
    # 발송 이력 헤더
    assert "발송 이력" in text


def test_history_tab_empty_when_no_run_store() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_store=None,
    )
    client = TestClient(app)
    resp = client.get("/", auth=AUTH)
    assert "아직 발송 이력이 없습니다" in resp.text


# ────────── Source edit (T1) ──────────


def test_edit_source_updates_fields(ctx: AdminCtx) -> None:
    rec = ctx.source_store.add("a.com", "A")
    resp = ctx.client.post(
        f"/sources/{rec.id}", auth=AUTH,
        data={"domain": "b.com", "name": "B", "description": "AI"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    updated = ctx.source_store.list_all()[0]
    assert updated.domain == "b.com"
    assert updated.name == "B"
    assert updated.description == "AI"


def test_edit_source_partial(ctx: AdminCtx) -> None:
    rec = ctx.source_store.add("a.com", "A")
    ctx.client.post(
        f"/sources/{rec.id}", auth=AUTH,
        data={"description": "메모만"},
        follow_redirects=False,
    )
    updated = ctx.source_store.list_all()[0]
    assert updated.domain == "a.com"  # 유지
    assert updated.description == "메모만"


def test_edit_source_unknown_returns_404(ctx: AdminCtx) -> None:
    resp = ctx.client.post(
        "/sources/999", auth=AUTH,
        data={"name": "X"}, follow_redirects=False,
    )
    assert resp.status_code == 404


# ────────── GET /api/runs/latest (T4) ──────────


def test_api_runs_latest_empty_when_no_run_store() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_store=None,
    )
    client = TestClient(app)
    resp = client.get("/api/runs/latest", auth=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"available": False}


def test_api_runs_latest_returns_recent_run() -> None:
    rs = InMemoryRunStore()
    r = rs.start_run()
    rs.mark_finished(r.run_id, status="success", article_count=8)

    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_store=rs,
    )
    client = TestClient(app)
    resp = client.get("/api/runs/latest", auth=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["run"]["run_id"] == r.run_id
    assert body["run"]["status"] == "success"
    assert body["run"]["article_count"] == 8


def test_api_runs_latest_returns_null_run_when_empty_store() -> None:
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        run_store=InMemoryRunStore(),
    )
    client = TestClient(app)
    resp = client.get("/api/runs/latest", auth=AUTH)
    assert resp.json() == {"available": True, "run": None}


# ────────── 자동 path 추천 (Phase H — 옵션 A) ──────────


from ai_news_scraping.search import PathSuggestion  # noqa: E402


def _make_app_with_discover(
    *,
    api_key: str | None = "fake-brave-key",
    discover_fn: Any = None,
    keyword_store: InMemoryKeywordStore | None = None,
) -> TestClient:
    return TestClient(create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=InMemorySubscriberStore(),
        scrape_state_store=InMemoryScrapeStateStore(),
        keyword_store=keyword_store or InMemoryKeywordStore(),
        source_store=InMemorySourceStore(),
        brave_search_api_key=api_key,
        discover_paths_fn=discover_fn,
    ))


def test_discover_paths_endpoint_returns_json_suggestions() -> None:
    captured: dict[str, Any] = {}

    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        captured["host"] = host
        captured["keyword"] = keyword
        captured["api_key"] = api_key
        return [
            PathSuggestion("/index", 13, 65.0, "https://openai.com/index/a/"),
            PathSuggestion("/research", 3, 15.0, "https://openai.com/research/b/"),
        ]

    client = _make_app_with_discover(discover_fn=fake_discover)
    resp = client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com", "keyword": "OpenAI"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "openai.com"
    assert body["keyword"] == "OpenAI"
    assert len(body["suggestions"]) == 2
    assert body["suggestions"][0] == {
        "prefix": "/index",
        "count": 13,
        "percentage": 65.0,
        "sample_url": "https://openai.com/index/a/",
    }
    assert captured == {
        "host": "openai.com",
        "keyword": "OpenAI",
        "api_key": "fake-brave-key",
    }


def test_discover_paths_endpoint_strips_www_and_lowercases_domain() -> None:
    captured: dict[str, Any] = {}

    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        captured["host"] = host
        return []

    client = _make_app_with_discover(discover_fn=fake_discover)
    client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "WWW.OpenAI.COM", "keyword": "AI"},
    )
    assert captured["host"] == "openai.com"


def test_discover_paths_endpoint_uses_active_keyword_default() -> None:
    """keyword 빈 → keyword_store 의 첫 번째 active 키워드 자동 사용."""
    captured: dict[str, Any] = {}

    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        captured["keyword"] = keyword
        return []

    kw_store = InMemoryKeywordStore()
    kw_store.add("LLM")
    kw_store.add("AI agents")
    client = _make_app_with_discover(
        discover_fn=fake_discover, keyword_store=kw_store
    )
    client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com"},
    )
    assert captured["keyword"] == "LLM"


def test_discover_paths_endpoint_falls_back_to_ai_when_no_keyword() -> None:
    """keyword_store 비었거나 active 없으면 'AI' default."""
    captured: dict[str, Any] = {}

    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        captured["keyword"] = keyword
        return []

    client = _make_app_with_discover(discover_fn=fake_discover)
    client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com"},
    )
    assert captured["keyword"] == "AI"


def test_discover_paths_endpoint_503_when_api_key_missing() -> None:
    client = _make_app_with_discover(api_key=None)
    resp = client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com"},
    )
    assert resp.status_code == 503
    assert "brave_search_api_key" in resp.text


def test_discover_paths_endpoint_400_when_domain_blank() -> None:
    client = _make_app_with_discover()
    resp = client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "  ", "keyword": "AI"},
    )
    assert resp.status_code == 400


def test_discover_paths_endpoint_400_on_value_error() -> None:
    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        raise ValueError("host must be non-empty")

    client = _make_app_with_discover(discover_fn=fake_discover)
    resp = client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com", "keyword": "AI"},
    )
    assert resp.status_code == 400


def test_discover_paths_endpoint_503_on_external_error() -> None:
    def fake_discover(host: str, keyword: str, *, api_key: str) -> list[PathSuggestion]:
        raise RuntimeError("Brave 429 rate limit")

    client = _make_app_with_discover(discover_fn=fake_discover)
    resp = client.post(
        "/admin/sources/discover-paths", auth=AUTH,
        data={"domain": "openai.com", "keyword": "AI"},
    )
    assert resp.status_code == 503
    assert "discover_paths failed" in resp.text


def test_discover_paths_endpoint_requires_auth() -> None:
    client = _make_app_with_discover()
    resp = client.post(
        "/admin/sources/discover-paths",
        data={"domain": "openai.com"},
    )
    assert resp.status_code == 401


def test_index_renders_discover_button_in_sources_panel(ctx: AdminCtx) -> None:
    """admin index 의 Sources 패널에 자동 path 검출 UI 가 렌더링됨."""
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    # 자동 검출 버튼 + 결과 컨테이너 둘 다 존재
    assert 'id="discover-btn"' in resp.text
    assert 'id="discover-result"' in resp.text
    assert "자동 path 검출" in resp.text
    # keyword 선택 input (H5)
    assert 'id="discover-keyword"' in resp.text
    # JS 가 호출하는 endpoint URL 명시
    assert "/admin/sources/discover-paths" in resp.text


def test_index_renders_per_row_discover_button(ctx: AdminCtx) -> None:
    """이미 등록된 source row 마다 🔍 path 검출 버튼이 렌더링됨 (H5)."""
    ctx.source_store.add("openai.com", "OpenAI")
    ctx.source_store.add("anthropic.com", "Anthropic")
    resp = ctx.client.get("/", auth=AUTH)
    assert resp.status_code == 200
    # 각 row 의 data-domain 속성에 호스트가 들어가야 JS 가 그 host 로 호출 가능
    assert 'class="row-discover-btn"' in resp.text
    assert 'data-domain="openai.com"' in resp.text
    assert 'data-domain="anthropic.com"' in resp.text
