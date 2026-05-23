from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from ai_news_scraping.admin import create_app
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
    assert "ai_news_scraping admin" in resp.text


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
