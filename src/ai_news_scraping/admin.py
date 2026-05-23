"""FastAPI admin 페이지 — 스크래핑 ON/OFF 토글 + 구독자 명단 + 검색 조건 관리.

CLAUDE.md §3 핵심 산출물 4: "심플 admin 페이지". 인증은 HTTPBasic — username 은
무시, password 만 ``admin_token`` 과 일치 검사 (constant-time).
React/SPA 안 씀 — Jinja2 단일 HTML 페이지.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .scrape_state_store import ScrapeStateStore
from .search_config_store import KeywordStore, SettingsStore, SourceStore
from .subscriber_store import SubscriberStore

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

# Module-level so FastAPI's dependency resolution can statically inspect it.
# (Closure-scoped HTTPBasic() caused credentials to be mis-classified as a
#  query param under fastapi 0.136 / starlette 1.0.)
_security = HTTPBasic()
_AdminCredentials = Annotated[HTTPBasicCredentials, Depends(_security)]


def create_app(
    *,
    admin_token: str,
    subscriber_store: SubscriberStore,
    scrape_state_store: ScrapeStateStore,
    keyword_store: KeywordStore | None = None,
    source_store: SourceStore | None = None,
    settings_store: SettingsStore | None = None,
    templates_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="ai_news_scraping admin")
    templates = Jinja2Templates(directory=str(templates_dir or DEFAULT_TEMPLATES_DIR))

    def require_admin(credentials: _AdminCredentials) -> None:
        # username 은 무시. password 만 constant-time 비교.
        if not secrets.compare_digest(credentials.password, admin_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin token",
                headers={"WWW-Authenticate": "Basic"},
            )

    auth_dep = [Depends(require_admin)]

    @app.get("/", response_class=HTMLResponse, dependencies=auth_dep)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "scrape_enabled": scrape_state_store.is_enabled(),
                "subscribers": subscriber_store.list_all(),
                "keywords": keyword_store.list_all() if keyword_store else [],
                "sources": source_store.list_all() if source_store else [],
                "settings": settings_store.get() if settings_store else None,
            },
        )

    @app.post("/scrape-enabled/toggle", dependencies=auth_dep)
    def toggle_scrape() -> RedirectResponse:
        scrape_state_store.toggle()
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/subscribers", dependencies=auth_dep)
    def add_subscriber(email: Annotated[str, Form()]) -> RedirectResponse:
        try:
            subscriber_store.add(email)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/subscribers/{subscriber_id}/delete", dependencies=auth_dep)
    def remove_subscriber(subscriber_id: int) -> RedirectResponse:
        subscriber_store.remove(subscriber_id)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # ────────── Keyword 라우트 (Phase F5) ──────────

    @app.post("/keywords", dependencies=auth_dep)
    def add_keyword(keyword: Annotated[str, Form()]) -> RedirectResponse:
        if keyword_store is None:
            raise HTTPException(status_code=503, detail="keyword store not configured")
        try:
            keyword_store.add(keyword)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/keywords/{keyword_id}/delete", dependencies=auth_dep)
    def remove_keyword(keyword_id: int) -> RedirectResponse:
        if keyword_store is None:
            raise HTTPException(status_code=503, detail="keyword store not configured")
        keyword_store.remove(keyword_id)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/keywords/{keyword_id}/toggle", dependencies=auth_dep)
    def toggle_keyword(keyword_id: int) -> RedirectResponse:
        if keyword_store is None:
            raise HTTPException(status_code=503, detail="keyword store not configured")
        current = next(
            (k for k in keyword_store.list_all() if k.id == keyword_id), None
        )
        if current is None:
            raise HTTPException(status_code=404, detail="keyword not found")
        keyword_store.set_active(keyword_id, not current.active)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # ────────── Source 라우트 (Phase F6) ──────────

    @app.post("/sources", dependencies=auth_dep)
    def add_source(
        domain: Annotated[str, Form()],
        name: Annotated[str, Form()],
    ) -> RedirectResponse:
        if source_store is None:
            raise HTTPException(status_code=503, detail="source store not configured")
        try:
            source_store.add(domain, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/sources/{source_id}/delete", dependencies=auth_dep)
    def remove_source(source_id: int) -> RedirectResponse:
        if source_store is None:
            raise HTTPException(status_code=503, detail="source store not configured")
        source_store.remove(source_id)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/sources/{source_id}/toggle", dependencies=auth_dep)
    def toggle_source(source_id: int) -> RedirectResponse:
        if source_store is None:
            raise HTTPException(status_code=503, detail="source store not configured")
        current = next(
            (s for s in source_store.list_all() if s.id == source_id), None
        )
        if current is None:
            raise HTTPException(status_code=404, detail="source not found")
        source_store.set_active(source_id, not current.active)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # ────────── Settings 라우트 (Phase F7) ──────────

    @app.post("/settings", dependencies=auth_dep)
    def update_settings(
        freshness: Annotated[str | None, Form()] = None,
        num_results_per_keyword: Annotated[int | None, Form()] = None,
        max_articles_for_summary: Annotated[int | None, Form()] = None,
        min_body_len: Annotated[int | None, Form()] = None,
    ) -> RedirectResponse:
        if settings_store is None:
            raise HTTPException(status_code=503, detail="settings store not configured")
        try:
            settings_store.update(
                freshness=freshness,
                num_results_per_keyword=num_results_per_keyword,
                max_articles_for_summary=max_articles_for_summary,
                min_body_len=min_body_len,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return app
