# IMPLEMENTATION_PLAN

> ralph 가 매 iteration 갱신하는 체크리스트.
> CLAUDE.md 의 §비전/사양 8 항목을 기반으로 도출된 task 목록.
> 망가지면 통째 폐기 (disposable).

---

## TODO

### Phase A — 인프라 & 환경

- [x] pyproject.toml + uv 환경 + src/tests 구조 + ruff/mypy/pytest 검증 명령 셋업
- [x] `.env.example` 작성 — `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`, `GEMINI_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_TOKEN`
- [x] `config.py` — pydantic-settings 로 환경변수 typed loader 작성
- [x] `keywords.yaml` + `sources.yaml` — 검색 키워드 5개 + 영어권 AI 매체 10개 화이트리스트 (도메인 분리용 config-driven) — `domains/ai_news/` + `domain_config.py` 로더
- [x] Supabase 스키마 정의 — `articles` (url unique, title, source, published_at, raw_html_excerpt, body_text, fetched_at), `subscribers` (email, active), `runs` (run_id, started_at, finished_at, article_count, status, error), `scrape_enabled` (단일 row 토글) — `supabase/migrations/0001_initial_schema.sql` + 적용 가이드 README

### Phase B — 도메인 파이프라인 (재사용 가능 구조)

- [x] `search.py` — Google Custom Search API 호출 wrapper. `q=keyword site:(d1 OR d2 ...) tbs=qdr:d` 한 호출에 매체 묶음. 키워드별 1 호출.
- [x] `extract.py` — trafilatura 본문 추출 wrapper. URL → (title, body_text). 실패 시 예외 + 화이트리스트 자동 제외 로그.
- [x] `store.py` — Supabase 클라이언트로 article upsert (url unique), dedup 처리
- [x] `summarize.py` — Gemini API 호출 wrapper. 영문 본문 N개 → 한국어 통합 트렌드 요약 (10~20건 기준)
- [x] `mail.py` — Gmail SMTP 발송 wrapper. 구독자 명단 BCC 일괄 발송. 제목·본문 템플릿.
- [x] `pipeline.py` — Phase B 모든 단계 orchestration. `run()` 단일 entry point.

### Phase C — Admin (심플)

- [x] `admin.py` — FastAPI 앱. 단일 HTML 페이지 (Jinja2 template) — 스크래핑 ON/OFF 토글 버튼 + 구독자 명단 추가/제거 form. `ADMIN_TOKEN` 으로 단순 인증.
- [x] `templates/admin.html` — 1 파일 HTML (React 안 씀)
- [x] (bonus) `subscriber_store.py` + `scrape_state_store.py` — admin 의존성, ArticleStore 와 동일 패턴 (InMemory + Supabase)

### Phase D — 운영 & 자동화

- [x] `cli.py` — `python -m ai_news_scraping.cli run` 진입점. `--dry-run` 옵션.
- [x] `.github/workflows/daily-digest.yml` — cron `40 23 * * *` (UTC = 08:40 KST) + 수동 트리거. secrets 주입.
- [x] `tests/` — 각 wrapper 단위 테스트 (mock 외부 API) + pipeline 통합 smoke test
- [x] `README.md` 갱신 — 셋업 / secrets 등록 / 로컬 dry-run / 운영 가이드

### Phase F — 검색 조건 admin 화 (yaml → DB)

> 대표님 피드백: 키워드·매체·운영옵션을 admin 페이지에서 운영 중 변경 가능해야 함.
> yaml 은 seed 용으로 유지 (도메인 재사용 starting point), DB 우선·yaml fallback.

- [x] (F1) `0002_search_admin.sql` 마이그레이션 — `ai_news.search_keywords` / `ai_news.search_sources` / `ai_news.search_settings` 3 테이블 + RLS + seed singleton row + 테스트
- [x] (F2) `search_config_store.py` 신규 — `KeywordStore`, `SourceStore`, `SettingsStore` 3 protocol + InMemory + Supabase 구현 + 테스트
- [x] (F3) `search_config_loader.py` 신규 — `load_search_config(stores, yaml_fallback) -> LoadedConfig` 헬퍼 (DB 우선, yaml fallback). pipeline.py 는 PipelineParams 매핑만 받으므로 변경 X — cli 가 loader 결과를 PipelineParams 로 빌드 (F4).
- [x] (F4) `cli.py` 의 `_entry_run` 이 store 들 초기화 + seed (DB 비었으면 yaml 에서 자동 import 1회) + loader 호출 → build_params
- [x] (F5) `admin.py` 키워드 라우트 — `POST /keywords` (add), `POST /keywords/{id}/delete`, `POST /keywords/{id}/toggle`. GET 은 메인 페이지 `/` 에 통합.
- [x] (F6) `admin.py` 매체 라우트 — `POST /sources` (domain + name), `POST /sources/{id}/delete`, `POST /sources/{id}/toggle`. GET 은 `/` 통합.
- [x] (F7) `admin.py` 설정 라우트 — `POST /settings` (freshness / num_results / max_articles / min_body_len 일괄 partial update). 폼은 `/` 통합.
- [x] (F8) `templates/admin.html` 탭 구조로 개편 — Overview / Keywords / Sources / Settings / Subscribers 5 탭 + URL hash deep-link
- [x] (F9) 통합 smoke test 갱신 — cli.run_command 를 통한 DB → PipelineParams 매핑 검증 + yaml fallback 검증 2 케이스
- [x] (F10) `CLAUDE.md` §6 + setup-guide.html §3 + README.md 운영 가이드 갱신 — admin 페이지 5탭 + 0002 마이그레이션 + seed/fallback 원칙

### Phase G — 강제발송 + 발송 이력 (대표님 추가 요청)

> 대표님 피드백:
> 1. "발송" 버튼 → "**강제발송**" 으로 이름 변경
> 2. 강제발송 = 바로 **직전 run 에서 다룬 article 들을 DB 에서 삭제** 후 발송 (모두 X, 직전 1회분만)
> 3. 발송 이력 다 남기기 — runs 테이블 활용 (어디서 언제 어떤 결과로 끝났는지)
> 4. yaml seed / DB 격리 / schema=ai_news 원칙 그대로 유지

- [x] (G1) `run_store.py` 신규 — `RunStore` protocol + InMemory + Supabase. `start_run() / mark_finished(run_id, status, article_count, error?, digest_text?) / list_recent(limit) / get_last_success()`. RunRecord dataclass + 테스트.
- [x] (G2) `store.py` 의 `ArticleStore` 에 `delete_by_run_id(run_id) -> int` 추가 (InMemory + Supabase 양쪽) + 테스트.
- [x] (G3) `pipeline.py` 가 `RunStore` 받아서 run 시작 (status=running) / 종료 (success|failed|skipped, article_count, digest_text) 기록. PipelineDeps 에 run_store 추가. 예외 시 runs.error 기록.
- [x] (G4) `cli.run_command` 에 `force: bool=False` 인자 추가. force=True 면 `run_store.get_last_success()` → `article_store.delete_by_run_id(last.run_id)` → 새 run 진행.
- [x] (G5) `admin.py` POST `/run-now` 에 `force: bool=True` Form (기본값) 추가. run_pipeline callback 시그니처 `(dry_run, force)` 로 확장. cli closure 가 force 전달.
- [x] (G6) `admin.html` Overview 카드 — "발송" → "**강제발송**" 으로 rename. force=True hidden input + dry-run 체크박스 유지. 토스트 메시지 4종 (force / live / dry-force / dry).
- [x] (G7) `admin.html` 에 새 탭 **"History"** — `run_store.list_recent(20)` 결과 표시 (run_id 8자 / 시작·종료 시각 / status 색상 / article_count / digest preview 또는 error).
- [x] (G8) 테스트는 각 G1~G7 commit 에서 동반 처리 (총 248 pass). CLAUDE.md §6 강제발송 + 발송 이력 원칙 추가, setup-guide.html 6 탭 + 강제발송 callout, README.md admin 페이지 6 탭 설명 갱신.

---

## 완료 조건 (PROJECT_DONE)

CLAUDE.md §3 의 4가지 핵심 산출물이 모두 코드 레벨에서 [x]:
1. ✅ 재사용 가능한 검색·수집 파이프라인 (Phase B `search.py` + `extract.py` + `store.py` + `domains/<name>/` config-driven)
2. ✅ LLM 통합 요약·번역기 (Phase B `summarize.py`)
3. ✅ 메일 발송기 (Phase B `mail.py` + Phase D `cli.py` + GH Actions cron)
4. ✅ 심플 admin 페이지 (Phase C `admin.py` + `templates/admin.html`)

성공 정의: 08:40 ± 30분 발송 / 10~20건 / 한국어 단일 (CLAUDE.md §4) — 코드 레벨에서 cron 시각·max_articles_for_summary·언어 설정 모두 충족.

ralph 자동 루프의 PROJECT_DONE 는 **여기까지** 입니다. 실제 운영 검증은 외부 API 키 발급 + 실제 HTTP/SMTP 호출이 필요하며 아래 hand-off 체크리스트로 분리합니다.

---

## 사람 검증 hand-off (PROJECT_DONE 이후 대표님 영역 — ralph 자동 범위 밖)

> 외부 API 키 발급 + 실제 발송 + GitHub 환경 트리거가 필요하므로 ralph 자동 진행 범위 밖입니다.
> 아래는 plan 의 task 가 아니라 **운영 안내서** — 체크박스 형식을 의도적으로 쓰지 않습니다 (ralph 의 plan 진행 게이트를 흐트리지 않기 위해).
> 대표님이 [`README.md`](./README.md) 의 "사전 준비" → "GitHub Actions 배포" 섹션을 따라 직접 진행하십시오.

순서:
1. Google CSE / Gemini / Gmail / Supabase API 키 5종 발급
2. Supabase 마이그레이션 `0001_initial_schema.sql` 적용
3. 로컬 `.env` 채움 + `uv run python -m ai_news_scraping.cli run --dry-run` 통과
4. 본인 1명만 구독자 등록 후 `--dry-run` 빼고 1회 실 발송 → 메일 도착 확인
5. GitHub repo secrets 8개 등록 + Actions 탭에서 수동 트리거 (dry_run=true 먼저, 그 다음 false)
6. cron 첫 자동 실행일 (다음날 08:40 KST) 의 메일 도착 확인

---

## DONE (참고용 로그)

- [x] (iteration 1) 프로젝트 골격 + 검증 명령 셋업
