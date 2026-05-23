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
- [ ] `pipeline.py` — Phase B 모든 단계 orchestration. `run()` 단일 entry point.

### Phase C — Admin (심플)

- [ ] `admin.py` — FastAPI 앱. 단일 HTML 페이지 (Jinja2 template) — 스크래핑 ON/OFF 토글 버튼 + 구독자 명단 추가/제거 form. `ADMIN_TOKEN` 으로 단순 인증.
- [ ] `templates/admin.html` — 1 파일 HTML (React 안 씀)

### Phase D — 운영 & 자동화

- [ ] `cli.py` — `python -m ai_news_scraping.cli run` 진입점. `--dry-run` 옵션.
- [ ] `.github/workflows/daily-digest.yml` — cron `40 23 * * *` (UTC = 08:40 KST) + 수동 트리거. secrets 주입.
- [ ] `tests/` — 각 wrapper 단위 테스트 (mock 외부 API) + pipeline 통합 smoke test
- [ ] `README.md` 갱신 — 셋업 / secrets 등록 / 로컬 dry-run / 운영 가이드

### Phase E — 검증 게이트

- [ ] 통합 smoke run — env 셋업 후 `--dry-run` 으로 5 키워드 × 10 매체 검색 → trafilatura 추출 → Gemini 요약 → 발송 직전까지 한 번 통과
- [ ] 본인 메일 1개 구독자로 실제 발송 1회 성공 확인
- [ ] GitHub Actions 에서 수동 트리거 1회 성공 확인

---

## 완료 조건 (PROJECT_DONE)

CLAUDE.md §3 의 4가지 핵심 산출물이 모두 [x]:
1. 재사용 가능한 검색·수집 파이프라인 (Phase B)
2. LLM 통합 요약·번역기 (Phase B summarize)
3. 메일 발송기 (Phase B mail + Phase D cron)
4. 심플 admin 페이지 (Phase C)

성공 정의: 08:40 ± 30분 발송 / 10~20건 / 한국어 단일 (CLAUDE.md §4)

---

## DONE (참고용 로그)

- [x] (iteration 1) 프로젝트 골격 + 검증 명령 셋업
