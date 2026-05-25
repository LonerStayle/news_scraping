"""FastAPI admin 페이지 — 스크래핑 ON/OFF 토글 + 구독자 명단 + 검색 조건 관리.

CLAUDE.md §3 핵심 산출물 4: "심플 admin 페이지". 인증은 HTTPBasic — username 은
무시, password 만 ``admin_token`` 과 일치 검사 (constant-time).
React/SPA 안 씀 — Jinja2 단일 HTML 페이지.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .run_store import RunStore
from .scrape_state_store import ScrapeStateStore
from .search_config_store import KeywordStore, SettingsStore, SourceStore
from .subscriber_store import SubscriberStore

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def _format_trigger_flag(*, dry_run: bool, force: bool) -> str:
    if dry_run:
        return "dry-force" if force else "dry"
    return "force" if force else "live"


def _compute_recommended(keywords: list[Any], sources: list[Any]) -> dict[str, Any]:
    """현재 active 키워드/소스 수 기반 스마트 권장 설정값 계산.

    공식:
    - AI 분석 기사 개수 = max(20, active_keywords × 5 + 10)
      (키워드 1개당 평균 통과 3~5건 가정 + 10 마진)
    - 키워드당 결과 수 = 20 (Brave free tier max, 항상 권장)
    - freshness: total = active_keywords × active_sources
        · ≥200 → "pd" (1일) — 매일 풍부
        · ≥50  → "pw" (1주) — 보통 운영
        · <50  → "pm" (1개월) — 결과 부족 방지
    - 최소 본문 길이 = 300 (paywall 방어 기본)

    참고: Brave 일 호출 수 = active_keywords (키워드 1개당 1 호출, 매체는 site: OR 묶음).
    """
    active_keywords = sum(1 for k in keywords if getattr(k, "active", True))
    active_sources = sum(1 for s in sources if getattr(s, "active", True))
    total = active_keywords * active_sources
    if total >= 200:
        freshness = "pd"
        freshness_label = "past day (1일)"
    elif total >= 50:
        freshness = "pw"
        freshness_label = "past week (1주)"
    else:
        freshness = "pm"
        freshness_label = "past month (1개월)"
    max_articles = max(20, active_keywords * 5 + 10)
    brave_calls_month = active_keywords * 30
    brave_cap_pct = round(brave_calls_month / 2000 * 100, 1)
    return {
        "active_keywords": active_keywords,
        "active_sources": active_sources,
        "num_results_per_keyword": 20,
        "max_articles_for_summary": max_articles,
        "freshness": freshness,
        "freshness_label": freshness_label,
        "min_body_len": 300,
        "brave_calls_per_day": active_keywords,
        "brave_calls_per_month": brave_calls_month,
        "brave_cap_pct": brave_cap_pct,
    }

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
    run_store: RunStore | None = None,
    # run_pipeline(dry_run, force) — 강제발송 시 force=True 로 직전 run article 삭제.
    run_pipeline: Callable[[bool, bool], Any] | None = None,
    auth_enabled: bool = True,
    templates_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="ai_news_scraping admin")
    templates = Jinja2Templates(directory=str(templates_dir or DEFAULT_TEMPLATES_DIR))

    # auth_enabled=False 면 HTTPBasic 의존성 자체를 라우트에서 빼서 팝업조차
    # 안 뜨게 한다. 로컬 전용 (127.0.0.1 만 바인딩) 인 경우 편의용.
    if auth_enabled:
        def require_admin(credentials: _AdminCredentials) -> None:
            if not secrets.compare_digest(credentials.password, admin_token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid admin token",
                    headers={"WWW-Authenticate": "Basic"},
                )

        auth_dep: list[Any] = [Depends(require_admin)]
    else:
        auth_dep = []

    @app.get("/", response_class=HTMLResponse, dependencies=auth_dep)
    def index(request: Request) -> HTMLResponse:
        kw_list = keyword_store.list_all() if keyword_store else []
        src_list = source_store.list_all() if source_store else []
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "scrape_enabled": scrape_state_store.is_enabled(),
                "subscribers": subscriber_store.list_all(),
                "keywords": kw_list,
                "sources": src_list,
                "settings": settings_store.get() if settings_store else None,
                "runs": run_store.list_recent(20) if run_store else [],
                "recommended": _compute_recommended(kw_list, src_list),
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

    @app.post("/sources/{source_id}", dependencies=auth_dep)
    def edit_source(
        source_id: int,
        domain: Annotated[str, Form()] = "",
        name: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        if source_store is None:
            raise HTTPException(status_code=503, detail="source store not configured")
        try:
            updated = source_store.update(
                source_id,
                domain=domain or None,
                name=name or None,
                description=description if description != "" else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="source not found")
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

    # ────────── 최근 run 상태 JSON (T4: 강제발송 폴링) ──────────

    @app.get("/api/runs/latest", dependencies=auth_dep)
    def get_latest_run() -> dict[str, Any]:
        if run_store is None:
            return {"available": False}
        recent = run_store.list_recent(1)
        if not recent:
            return {"available": True, "run": None}
        r = recent[0]
        return {
            "available": True,
            "run": {
                "run_id": r.run_id,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "article_count": r.article_count,
                "error": r.error,
            },
        }

    # ────────── 즉시 발송 (지금 보내기) ──────────

    @app.post("/run-now", dependencies=auth_dep)
    def run_now(
        background: BackgroundTasks,
        dry_run: Annotated[bool, Form()] = False,
        force: Annotated[bool, Form()] = True,  # admin "강제발송" 기본값
    ) -> RedirectResponse:
        if run_pipeline is None:
            raise HTTPException(
                status_code=503, detail="run_pipeline not configured"
            )
        background.add_task(run_pipeline, dry_run, force)
        flag = _format_trigger_flag(dry_run=dry_run, force=force)
        return RedirectResponse(
            url=f"/?triggered={flag}", status_code=status.HTTP_303_SEE_OTHER
        )

    # ────────── Settings 라우트 (Phase F7) ──────────

    @app.post("/settings", dependencies=auth_dep)
    def update_settings(
        freshness: Annotated[str | None, Form()] = None,
        num_results_per_keyword: Annotated[int | None, Form()] = None,
        max_articles_for_summary: Annotated[int | None, Form()] = None,
        min_body_len: Annotated[int | None, Form()] = None,
        send_hour: Annotated[int | None, Form()] = None,
        send_minute: Annotated[int | None, Form()] = None,
    ) -> RedirectResponse:
        if settings_store is None:
            raise HTTPException(status_code=503, detail="settings store not configured")
        try:
            settings_store.update(
                freshness=freshness,
                num_results_per_keyword=num_results_per_keyword,
                max_articles_for_summary=max_articles_for_summary,
                min_body_len=min_body_len,
                send_hour=send_hour,
                send_minute=send_minute,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return app
