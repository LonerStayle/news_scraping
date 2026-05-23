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

## 사람 검증 hand-off 체크리스트 (PROJECT_DONE 무관)

> 외부 API 키 발급 + 실제 발송 + GitHub 환경 트리거가 필요하므로 ralph 자동 진행 범위 밖입니다. 대표님이 [`README.md`](./README.md) 의 "사전 준비" → "GitHub Actions 배포" 섹션을 따라 직접 진행하십시오.

- [ ] (사람) Google CSE / Gemini / Gmail / Supabase API 키 5종 발급
- [ ] (사람) Supabase 마이그레이션 `0001_initial_schema.sql` 적용
- [ ] (사람) 로컬 `.env` 채움 + `uv run python -m ai_news_scraping.cli run --dry-run` 통과 (Phase E1)
- [ ] (사람) 본인 1명만 구독자 등록 후 `--dry-run` 빼고 1회 실 발송 → 메일 도착 확인 (Phase E2)
- [ ] (사람) GitHub repo secrets 8개 등록 + Actions 탭에서 수동 트리거 (dry_run=true 먼저, 그 다음 false) (Phase E3)
- [ ] (사람) cron 첫 자동 실행일 (다음날 08:40 KST) 의 메일 도착 확인

---

## DONE (참고용 로그)

- [x] (iteration 1) 프로젝트 골격 + 검증 명령 셋업
