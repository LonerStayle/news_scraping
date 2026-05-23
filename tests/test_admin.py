from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from ai_news_scraping.admin import create_app
from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
from ai_news_scraping.subscriber_store import InMemorySubscriberStore

ADMIN_TOKEN = "test-token"
AUTH = ("admin", ADMIN_TOKEN)


@dataclass
class AdminCtx:
    client: TestClient
    sub_store: InMemorySubscriberStore
    scrape_store: InMemoryScrapeStateStore


@pytest.fixture
def ctx() -> AdminCtx:
    sub_store = InMemorySubscriberStore()
    scrape_store = InMemoryScrapeStateStore(initial=True)
    app = create_app(
        admin_token=ADMIN_TOKEN,
        subscriber_store=sub_store,
        scrape_state_store=scrape_store,
    )
    return AdminCtx(
        client=TestClient(app),
        sub_store=sub_store,
        scrape_store=scrape_store,
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
