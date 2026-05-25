# HANDOFF — 뉴스 스크래핑 (`ai_news_scraping` 폴더)

> 작성일: 2026-05-23 · 최근 갱신: **2026-05-25 (2회차)** · 인계 시점 commit: `0bb7d86` · **329 tests pass**
>
> 📌 서비스명은 **뉴스 스크래핑** 입니다. 폴더 / 패키지명 `ai_news_scraping` 는 첫 use case 가 AI 도메인이라 붙은 historical 이름이며, 도구 자체는 generic (AI 외 도메인도 동일 파이프라인으로 운영 가능 — `domains/<이름>/` 추가만으로).

> **2026-05-25 (2회차) 갱신 요약**: ① 운영 사고 1번 — 메일 결과가 **Anthropic 1개 매체로 92% 쏠리는 편향**. 원인: **사용자 등록 path 가 실제 글 URL 패턴과 불일치** (예: `openai.com/news` 등록인데 실제 글은 `/index/<slug>`). 매체 14개 active 인데 13개 매체 결과 0. ② 해결: cap 권장 공식 강화 (×1.5 → /2 분산 강제), `_looks_like_article_url` 휴리스틱 완화 (`/index` `/blog` 등 일반 글 path 더 통과), search 디버그 로깅 (단계별 reject 카운트). ③ 운영 측 변경 필요 — admin Sources path 수정 또는 호스트만 등록 (§12-C 참조). ④ **다음 세션 작업: 옵션 A — 자동 path 추천** (도메인만 입력하면 Brave 호출로 실제 글 path 자동 검출 + 사용자 추천). ⑤ commits `d053709..0bb7d86` (10개 추가). 320 → 329 tests (+9).

이 문서를 위에서 아래로 한 번 읽으시면 프로젝트의 **무엇·왜·어떻게·어디** 를 다 알 수 있습니다. 다음 인계자가 첫 번째로 읽을 단일 문서.

> **2026-05-25 갱신 요약**: ① admin-send-schedule 피처 완료 — admin Settings 에서 **발송 시각 (HH:MM KST) 직접 변경** 가능. GitHub Actions cron 이 매 5분 sweep (`'*/5 23,0 * * *'`) 로 변경되고 cli 시각 게이트가 ±2분 윈도우 매칭 시점만 통과 + `has_success_today` 로 중복 방지. ② 284 → 319 tests (+35). ③ 운영 셋업 가이드는 [`cron-setup-guide.html`](./cron-setup-guide.html) (멋진 다크 글래스 디자인) 에서. ④ 자세한 흐름은 §6-3, §12-B, `docs/features/2026-05-24-admin-send-schedule/` 참조.

> **2026-05-24 갱신 요약**: ① Brave `site:` 의 path 거부 (422) 사고 → host-only 임시 안전장치 (commit `7d85e69`) → 정식 path-prefix 클라이언트 필터 (T1~T8, `0117a93..680eb1a`). admin Sources 폼에 host 또는 host/path 둘 다 입력 가능. ② 268 → 284 tests (+16). ③ 자세한 흐름은 §9-8, §12-A, `docs/features/2026-05-24-search-path-prefix/` 참조.

---

## 1. 프로젝트 개요 (10초)

**매일 아침 영어권 AI 매체의 기사를 자동 수집·요약·한국어로 정리해 메일로 전달**하는 서비스. ~10명 구독자, 매일 **08:40 KST** 발송.

핵심 산출물 (CLAUDE.md §3):
1. **재사용 가능한 검색·수집 파이프라인** — 키워드/매체 config 만 갈아끼우면 다른 도메인 (헬스케어/핀테크 등) 에 그대로 사용
2. **LLM 통합 요약·번역기** — 영문 N건 → 한국어 트렌드 정리본
3. **메일 발송기** — Gmail SMTP BCC 일괄
4. **admin 페이지** — 스크래핑 토글 + 구독자/키워드/매체/설정 관리 + 강제발송 + 발송 이력

**월 운영 비용 cap: $0** (전부 free tier 안에서 운영, CLAUDE.md §7).

---

## 2. 아키텍처 한눈에

```
┌──────────────────────────────────────────────────────────────────┐
│   GitHub Actions cron  (매일 23:40 UTC = 08:40 KST)              │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
                ┌────────────────────────┐
                │  cli.py: run_command   │
                └────────────┬───────────┘
                             ▼
   ┌─────────────────────────────────────────────────────────┐
   │ pipeline.run() — 5 단계                                  │
   │                                                          │
   │  1) search.py        Brave Search 3위일체 검색           │
   │  2) extract.py       trafilatura 본문 추출 (Chrome UA)   │
   │  3) store.py         Supabase articles upsert + URL 정규화│
   │  4) summarize.py     Gemini 한국어 통합 트렌드 정리      │
   │  5) mail.py          Gmail SMTP BCC 일괄 발송            │
   │                                                          │
   │  + run_store.py     발송 이력 (runs 테이블)              │
   └─────────────────────────────────────────────────────────┘

   admin.py (FastAPI + Jinja2 SSR)  — port 6661
   ─────────────────────────────────────────────
   · Overview  : 스크래핑 ON/OFF + ▶ 강제발송 + 요약
   · Keywords  : 추가/삭제/active 토글
   · Sources   : 추가/삭제/토글 + ✏ inline edit (domain/name/description)
   · Settings  : freshness / num_results / max_articles / min_body_len
   · Subscribers: 메일 명단
   · History   : 최근 20개 run (status/article_count/digest preview)
```

자세한 시각화: 브라우저로 [`architecture.html`](./architecture.html) 열기 (인터랙티브 탭).

---

## 3. 현재 상태

| 영역 | 상태 |
|------|------|
| 코드 산출물 | ✅ Phase A~G + search-path-prefix + admin-send-schedule + per-source cap + 권장값 카드 + 휴리스틱 완화 + cron 튜닝 (T1~T15, 2026-05-25 2회차) |
| 테스트 | ✅ **329 passed** (lint/mypy/pytest 모두 exit 0) |
| API 키 발급 | ✅ Brave / Gemini / Gmail / Supabase / Admin token |
| Supabase 마이그레이션 | ⚠️ **확인 필요**: 0001 + 0002 + 0003 + 0004 + **0005 (per-source cap)** 적용 여부 |
| Brave site: 422 사고 (5/24) | ✅ 해결 — host-only 임시 + 정식 path-prefix 클라이언트 필터 |
| GitHub repo + cron | ✅ remote push 됨 (`github.com/LonerStayle/news_scraping`). cron 매 5분 윈도우 활성. 단 secrets 8개 등록 + 첫 수동 trigger 검증은 **`cron-setup-guide.html`** 참조 |
| 매체 편향 사고 (5/25) | ⚠️ **미해결** — 14 매체 active 인데 Anthropic 1개로 92% 쏠림. 원인: **사용자 등록 path 가 실제 글 URL 과 불일치**. 옵션 A (자동 path 추천) 다음 세션 작업 (§12-C) |
| admin Sources path 운영 | ⚠️ 사용자가 path 정확히 등록 어려움 (실제 글 URL 패턴 모름). 옵션 A 까진 호스트만 등록 + 휴리스틱 권장 |
| 디버그 로깅 | ✅ `pipeline.py` + `search.py` 단계별 reject 카운트 (`Brave RAW`, `unknown_host`, `non_article`, `path_mismatch`) — 운영 진단용 |
| 로컬 실 발송 | ✅ 1회 성공 (대표님 본인 메일 수신 확인) |
| DB row 정리 | 강제발송 후 `truncate ai_news.articles, ai_news.runs restart identity cascade;` 로 리셋 가능 |

### 대표님 본인 점검 체크리스트 (운영 시작 전)

1. [ ] Supabase Dashboard → Table Editor → schema `ai_news` 에 **7 테이블** 보이는지 확인
   - 0001: `articles` / `subscribers` / `runs` / `scrape_enabled`
   - 0002: `search_keywords` / `search_sources` / `search_settings`
   - 0003: `search_sources.description` 컬럼 존재 (alter table)
   - **0004: `search_settings.send_hour` + `send_minute` 컬럼 존재 (default 8, 40)**
2. [ ] Supabase Settings → API → "Exposed schemas" 에 `ai_news` 추가됨
3. [ ] `.env` 에 8개 환경변수 + `ADMIN_AUTH_ENABLED=false` (로컬용) + `SUPABASE_SCHEMA=ai_news`
4. [ ] `make dry-run` 1회 통과 → articles 테이블에 row 안 쌓이는지 확인 (T2 dry-run dedup 함정 적용)
5. [ ] `make admin` 후 `http://127.0.0.1:6661` 접속 → 6탭 모두 정상 동작
6. [ ] **Sources 탭에서 path 입력 테스트** — `openai.com/research` 등록 → ▶ 강제발송 → 메일에서 그 prefix 결과만 통과되는지 확인
7. [ ] **Settings 탭에서 발송 시각 입력 칸 2개 보이는지 + 09:15 같은 값으로 변경 → Overview 에 "09:15 KST" 표시 확인**
8. [ ] **GitHub Actions secrets 8개 등록 + Run workflow 수동 1회** — 자세히는 [`cron-setup-guide.html`](./cron-setup-guide.html) 참조

---

## 4. 자주 쓰는 명령 (Makefile)

```bash
make help          # 명령 목록
make sync          # 의존성 설치 (uv sync --dev)
make admin         # admin 웹 UI (port 6661)
make run           # 매일 발송 파이프라인 1회 (실 발송)
make dry-run       # 메일 발송 없이 흐름 검증
make test          # pytest
make lint          # ruff check
make typecheck     # mypy
make check         # lint + typecheck + test (commit 직전 게이트)
make fmt           # ruff format + check --fix
make clean         # 캐시 정리
```

환경변수 override:
```bash
ADMIN_PORT=8080 make admin       # 다른 포트
DOMAIN=health_news make run      # 다른 도메인
```

---

## 5. 디렉토리 구조

```
ai_news_scraping/
├── .env.example                # 환경변수 키 + 발급 안내
├── .github/workflows/
│   └── daily-digest.yml        # 매일 23:40 UTC cron
├── domains/
│   └── ai_news/                # 키워드 + 매체 화이트리스트 (YAML seed)
│       ├── keywords.yaml       # 5개 검색 키워드
│       └── sources.yaml        # 10개 영어권 AI 매체
├── src/ai_news_scraping/
│   ├── cli.py                  # `python -m ai_news_scraping.cli run|admin`
│   ├── config.py               # pydantic-settings env loader
│   ├── domain_config.py        # YAML 로더
│   ├── search.py               # Brave Search 3위일체
│   ├── extract.py              # trafilatura + 브라우저 UA
│   ├── store.py                # ArticleStore (Supabase + InMemory)
│   ├── subscriber_store.py
│   ├── scrape_state_store.py
│   ├── search_config_store.py  # Keyword/Source/Settings store
│   ├── search_config_loader.py # DB 우선 / yaml fallback
│   ├── run_store.py            # 발송 이력 (runs 테이블)
│   ├── summarize.py            # Gemini 한국어 통합 요약
│   ├── mail.py                 # Gmail SMTP BCC
│   ├── pipeline.py             # end-to-end 5단계 orchestration
│   └── admin.py                # FastAPI admin
├── supabase/migrations/
│   ├── 0001_initial_schema.sql        # 4 핵심 테이블 + ai_news schema 격리
│   ├── 0002_search_admin.sql          # admin 운영 3 테이블
│   ├── 0003_source_description.sql    # search_sources.description 컬럼
│   └── 0004_send_schedule.sql         # search_settings.send_hour/send_minute (admin-send-schedule)
├── templates/admin.html        # Linear/Vercel dark + glassmorphism SSR
├── tests/                      # 259 tests
├── docs/features/              # ralph 작업 history (Phase F/G/fast-tasks)
├── CLAUDE.md                   # 비전·사양 (동결됨, vision-intake 가 채움)
├── PROMPT.md                   # ralph 행동 매뉴얼
├── IMPLEMENTATION_PLAN.md      # Phase A~G 완료 체크리스트
├── AGENTS.md                   # 검증 명령 (lint/typecheck/tests)
├── architecture.html           # 인터랙티브 아키텍처 문서
├── setup-guide.html            # 운영 셋업 시각 가이드
├── Makefile                    # 단축 명령
├── pyproject.toml              # uv + 의존성
└── README.md                   # 프로젝트 운영 가이드
```

---

## 6. 핵심 운영 흐름

### 6-1. 매일 자동 발송 (대표님 손 X)

1. GitHub Actions cron 이 **`*/5 23,0 * * *` UTC = KST 08:00~09:50 매 5분** 트리거 (일 22회 sweep)
2. workflow 가 `uv sync --frozen` → `python -m ai_news_scraping.cli run`
3. `cli.run_command()` — 5 게이트 순차 통과:
   - **게이트 ①**: scrape_enabled OFF → skip (admin 토글)
   - **게이트 ②**: subscribers 비어 있음 → skip
   - **게이트 ③ (NEW, admin-send-schedule)**: 현재 KST 시각이 `(send_hour, send_minute)` 의 ±2분 윈도우 밖 → skip (runs 추가 X)
   - **게이트 ④ (NEW, admin-send-schedule)**: `runs.has_success_today(now_kst)` 가 True → skip (중복 발송 차단)
   - 통과 시 `pipeline.run()` 호출
4. `pipeline.run()`:
   - `run_store.start_run()` → uuid + status=running 기록
   - 키워드별 Brave Search (1.2초 sleep, rate limit 우회)
   - URL 필터 (카테고리/홈페이지 차단) + trafilatura 본문 추출
   - DB upsert (articles 테이블, url unique)
   - Gemini 통합 요약 (한국어 마크다운)
   - Gmail SMTP BCC 발송
   - `run_store.mark_finished(status=success, article_count=N, digest_text=...)`

> 💡 매 5분 trigger 12회 중 1회만 진짜 발송. 나머지 11회는 outside-window 또는 already-sent-today 로 즉시 skip (DB row 추가 X). free tier 비용 ~월 720분 (cap 의 36%).

### 6-3. 발송 시각 변경 (admin Settings)

워크플로 파일 / git push 불필요. admin Settings 탭의 "**발송 시각 (KST)**" hour/minute 입력 칸 2개 → 저장 → 다음 cron trigger 부터 즉시 반영. 자세한 흐름: [`cron-setup-guide.html`](./cron-setup-guide.html) §6.

### 6-2. admin 페이지 (대표님이 운영 중 사용)

`make admin` → `http://127.0.0.1:6661`

- **Overview**: 스크래핑 ON/OFF 토글 + ▶ **강제발송** (직전 run 기사 삭제 후 새 발송) + 실시간 spinner + History 자동 갱신
- **Keywords**: 추가/active 토글/삭제
- **Sources**: 추가/active 토글/삭제 + ✏ **인라인 수정** (domain/name/description)
- **Settings**: freshness / num_results / max_articles / min_body_len 일괄 저장
- **Subscribers**: 메일 명단
- **History**: 최근 20개 run 의 상태 + 요약 미리보기

> 💡 URL hash deep-link: `/#keywords`, `/#sources`, `/#history` 등

---

## 7. 데이터 모델

모든 테이블은 **`ai_news` schema** 안 (CLAUDE.md §6 격리 원칙).

### 0001_initial_schema.sql (4 테이블)

- `ai_news.articles` — 수집 기사. `url unique` + `run_id` (강제발송 시 삭제 키)
- `ai_news.subscribers` — 메일 명단 (`email unique`, `active`)
- `ai_news.runs` — 발송 이력 (`run_id uuid pk`, `status` check 4-state, `article_count`, `error`, `digest_text`)
- `ai_news.scrape_enabled` — 싱글톤 토글 (`id=1`)

### 0002_search_admin.sql (3 테이블)

- `ai_news.search_keywords` — 키워드 admin (`keyword unique`, `active`)
- `ai_news.search_sources` — 매체 admin (`domain unique`, `name`, `active`)
- `ai_news.search_settings` — 싱글톤 운영 설정 (4 필드 + range/enum check)

### 0003_source_description.sql

- `ai_news.search_sources.description` 컬럼 추가 (NULL OK)

### 0004_send_schedule.sql (admin-send-schedule, 2026-05-25)

- `ai_news.search_settings.send_hour smallint NOT NULL DEFAULT 8 CHECK 0-23` 추가
- `ai_news.search_settings.send_minute smallint NOT NULL DEFAULT 40 CHECK 0-59` 추가
- 마이그레이션 시 기존 row (`id=1` 싱글톤) 는 default (8, 40) 로 채움 = 기존 cron 23:40 UTC 와 동일

**RLS**: 모든 테이블 활성화. `service_role` 키만 통과 (anon/authenticated 차단).

---

## 8. 외부 의존성 (모두 free tier)

| 영역 | 서비스 | 월 cap | 우리 사용량 | 인증 |
|------|--------|--------|-------------|------|
| 검색 | **Brave Search** | 2,000 | ~150 (일 5×30) | `X-Subscription-Token` header |
| 본문 fetch | requests + trafilatura | — | 일 ~50 | Chrome 120 UA |
| LLM | **Gemini** (현재 `gemini-3.5-flash`) | 분 15 RPM | 일 1회 | `?key=$GEMINI_API_KEY` |
| DB | **Supabase Postgres** | 500MB | ~수MB/년 | `SUPABASE_SERVICE_ROLE_KEY` JWT |
| 메일 | **Gmail SMTP** | 일 500 | 일 1회 × N명 BCC | 앱 비밀번호 |
| 스케줄러 | **GitHub Actions** | 월 2,000분 (private) | 월 ~15분 | repository secrets |

> ⚠️ **Brave rate limit**: Free tier = 1 query/sec. `pipeline.run()` 이 키워드 사이 1.2초 sleep 으로 우회.

---

## 9. 알려진 함정 (반드시 알아야 할 것)

### 9-1. 검색엔진 이전 이력

- **이전**: Google Custom Search API → 신규 Cloud project 에서 `PERMISSION_DENIED` 빈번 + 발급 단계 복잡 → **Brave Search 로 교체** (commit `8601e1d`)
- Google CSE 로 돌아가지 마십시오 — 같은 함정 재발 가능

### 9-2. trafilatura 의 기본 fetch 가 봇 차단됨

- `trafilatura.fetch_url` 의 기본 User-Agent 는 `trafilatura/X.X` → openai.com/anthropic.com 등이 403 차단
- 우리는 `extract.fetch_html_with_browser_ua` 로 교체 (Chrome 120 UA) — commit `67a5e8d`
- 기본 fetch 로 되돌리지 마십시오

### 9-3. dry-run + force 의 dedup 함정

- 이전: dry-run 도 articles 테이블에 저장 → 직후 실 발송 시 dedup 으로 다 막힘
- 현재: T2 commit (`f5f3984`) 으로 dry-run 시 store skip
- 만약 발송이 자꾸 articles=0 으로 끝나면 `delete from ai_news.articles;` 한 번

### 9-4. Brave URL 필터 휴리스틱 (search.py)

- `_looks_like_article_url()` 가 카테고리/홈페이지 차단:
  - path segment < 2 → 차단
  - 첫 segment ∈ {category, tag, author, ...} → 차단
  - 마지막 segment 길이 < 10 → 차단 (`/models/`, `/products/x/` 같은 짧은 페이지)
- 일부 진짜 기사 slug 가 너무 짧으면 같이 막힐 수 있음. 운영 중 발견되면 `_MIN_LAST_SEGMENT_LEN` 조정.

### 9-5. Supabase schema 노출 설정

- 0001/0002/0003 마이그레이션 적용 후 Supabase Dashboard → Settings → API → **"Exposed schemas"** 에 `ai_news` 명시적 추가 필요
- 안 하면 PostgREST 가 `Invalid schema: ai_news` 로 차단

### 9-6. Gmail 앱 비밀번호 16자리

- 공백 포함된 16자리가 표시되는데, `.env` 에는 **공백 제거** 후 입력
- 분실 시 재발급 후 `.env` + GitHub secrets 양쪽 갱신

### 9-7. Gemini 모델명

- 코드 기본값: `gemini-2.5-flash` (안정)
- 대표님 `.env`: `gemini-3.5-flash` (실제 동작 확인됨)
- Google AI Studio 가 "2.x deprecate" 안내 띄울 수 있음 — 그래도 당분간 동작

### 9-8. Brave Search `site:` 는 **호스트만** — 경로 X (코드 주석 + 클라이언트 필터로 흡수)

- `site:openai.com` ✅ / `site:openai.com/research` ❌ → **422 Unprocessable Entity** 로 쿼리 전체 거부
- 사고 이력: 대표님이 admin Sources 에 `openai.com/research` 류 URL 을 넣어 3회 연속 강제발송이 `status=skipped` 로 끝나고 메일 미수신 (2026-05-24)
- **현재 정식 형태** (commits `7d85e69` → `T1~T7` 갱신): admin 입력은 **host 또는 host/path 둘 다 허용** 하되, Brave 호출 시점에 host 만 추출해 전달하고 클라이언트 측 `_matches_path_prefix` (search.py) 가 segment-aware 매칭으로 path 필터 적용. 스킴/포트/쿼리/공백 등은 여전히 400 reject.
- search.py 의 `build_query` 함수 docstring 에 함정 명시 → 미래 누군가 "그냥 path 도 site: 에 통과시키자" 회귀 방지

---

## 10. CLAUDE.md 정책 (반드시 지킬 것)

CLAUDE.md §6 의 두 가지 원칙:

### 🔒 DB schema 격리 — `ai_news` 만 사용

- 새 테이블 추가 시 **`ai_news.<table>`** 형식. `public.<table>` 금지
- 마이그레이션은 `create schema if not exists ai_news;` 로 시작
- 코드: `client.schema(settings.supabase_schema).table(...)` 패턴
- Dashboard 의 "Exposed schemas" 에 `ai_news` 추가 필수

### 🎛️ 검색 조건 admin 운영 — yaml = seed, DB = source of truth

- `domains/<name>/*.yaml` 은 첫 부팅용 seed
- 그 후 모든 변경은 admin → DB
- pipeline 은 `load_search_config(stores, fallback=yaml)` 로 결정

### 🔁 강제발송 + 발송 이력

- `runs` 테이블이 source of truth
- 강제발송 = 직전 success run 의 article 삭제 후 새 run
- cron 자동은 `force=False` (기본 dedup)

### 새 검색 조건 필드 추가 시 6 곳 갱신

1. 마이그레이션 SQL
2. `search_config_store.SearchSettings` dataclass
3. `search_config_loader.LoadedConfig`
4. `pipeline.PipelineParams`
5. `admin.py` POST 라우트
6. `admin.html` 폼

---

## 11. 비상 대응

### 시나리오 A: cron 이 실패함

1. GitHub Actions 탭 → Daily AI News Digest → 빨간 X 표시된 run 클릭
2. 로그 확인
3. 일반적 원인:
   - Brave 429 → 1~2시간 대기 후 수동 트리거
   - Gemini API key invalid → AI Studio 에서 재발급 + secret 갱신
   - SMTP 인증 실패 → 앱 비밀번호 재발급
   - Supabase 일시중지 → Dashboard 접속 1회 + 5분 대기

### 시나리오 B: 발송 품질이 떨어짐 (기사 너무 적음)

1. admin → Settings 탭
2. `freshness` → `pm` (1개월) 로 늘리기
3. `num_results_per_keyword` → 20 (max) 확인
4. Sources 탭에서 active 매체 수 확인 (10개 이상 권장)
5. 저장 → 다음 cron 또는 강제발송으로 검증

### 시나리오 C: 며칠 동안 발송 멈추고 싶음 (휴가 등)

1. admin → Overview → 자동 스크래핑 토글 OFF
2. 복귀 후 다시 ON

### 시나리오 D: 동일 기사가 반복 발송됨 (이론상 X 지만)

- `delete from ai_news.articles where fetched_at > now() - interval '7 days';` (SQL Editor)
- 또는 admin "▶ 강제발송" 클릭 (직전 run 기사만 삭제)

---

## 12. 다음 개선 후보 (필요하면)

비전 §3 의 4 핵심 산출물은 모두 완료. 운영하면서 다음 후보 발견:

| 우선순위 | 후보 | 작업량 |
|---------|------|--------|
| ~~🔥 ⭐⭐⭐⭐~~ ✅ **완료** | ~~매체 path-prefix 클라이언트 필터~~ — 2026-05-24 구현 완료. commits `T1~T7`. admin Sources 폼에 host 또는 host/path 둘 다 입력 가능. | — |
| ~~🔥 ⭐⭐⭐⭐~~ ✅ **완료** | ~~admin 에서 발송 시각 변경~~ — 2026-05-25 구현 완료. commits `53f4b38..a3edf23`. admin Settings 탭에서 HH:MM KST 입력. cron 매 5분 sweep + ±2분 윈도우 (T11 튜닝). | — |
| ~~🔥 ⭐⭐⭐⭐~~ ✅ **완료** | ~~매체별 cap (per-source cap)~~ — 2026-05-25 구현 (T14). 마이그레이션 0005 + admin Settings "매체당 최대 결과 수" 폼. | — |
| ~~🔥 ⭐⭐⭐⭐~~ ✅ **완료** | ~~Settings 탭 스마트 권장값~~ — 2026-05-25 구현 (T13). active 키워드/소스 수 기반 자동 계산 카드. 권장 공식 ×1.5 → /2 분산 강제 fix. | — |
| 🔥 ⭐⭐⭐⭐⭐ **NEXT 세션** | **옵션 A — 자동 path 추천** (§12-C 참조) | 1 PRD 사이클 (~1시간) |
| ⭐⭐⭐ | runs.scheduled_at 또는 trigger 종류 (cron/admin/manual) 컬럼 추가 | 1 commit |
| ⭐⭐ | History 탭에서 특정 run 의 article 목록 보기 (drill-down) | 2~3 commit |
| ⭐⭐ | admin 페이지에 본인 메일 즉시 발송 (test recipient) 기능 | 1 commit |
| ⭐ | 매체별 추출 성공률 통계 (sources 탭에 last_extract_status) | 3~4 commit |
| ⭐ | 다국어 발송 (한국어 + 영어 원문 병기) — 비전 §5 의 "한국어 단일" 정책 변경 필요 |  |

---

### 12-B. ✅ admin 에서 발송 시각 변경 — 완료 (2026-05-25)

**완료 commits**: T1 (`53f4b38`) / T2 (`a979b39`) / T3 (`bbf4f88`) / T4 (`38b5ba3`) / T5 (`c4629ee`) / T6 (`dc79b24`) / T7 (`b456013`) / T8 log (`7a5e217`) / T9 html (`a3edf23`).

**최종 형태**:
- admin Settings 탭에 `send_hour` (0-23) + `send_minute` (0-59) 입력 칸 2개 추가
- 마이그레이션 0004 가 `search_settings` 에 두 컬럼 추가 (default 8:40)
- `cli.run_command()` 진입 직후 시각 게이트 — `(send_hour, send_minute) ± 5분 윈도우` 매칭 시점만 통과, 아니면 즉시 return (runs 추가 X)
- `run_store.has_success_today(now_kst)` 가 같은 KST 일자 success 존재 시 skip (중복 방지)
- `.github/workflows/daily-digest.yml` cron 을 `'40 23 * * *'` → `'*/5 23,0 * * *'` 으로 변경 (KST 08:00~09:50 매 5분 sweep, 일 22회)
- `force=True` (admin 강제발송) 와 `dry_run=True` (로컬) 는 시각 게이트 무시
- 자세한 흐름: `docs/features/2026-05-24-admin-send-schedule/` 의 PRD (CH-001) → tech-design (CH-002) → plan (CH-003) → 구현 batch (CH-004) → 검증 (CH-005)

**대표님 셋업 방법**: 별도 가이드 [`cron-setup-guide.html`](./cron-setup-guide.html) 참조 (멋진 다크 글래스 디자인, ~15분 소요).

**활용 예** (admin Settings 에 저장):

| 입력값 | 동작 |
|--------|------|
| `send_hour=8, send_minute=40` (기본값) | KST 08:40 발송 |
| `send_hour=9, send_minute=15` | KST 09:15 발송 (cron 09:10 또는 09:20 trigger 가 윈도우 안) |
| `send_hour=8, send_minute=0` | KST 08:00 발송 (cron 08:00 trigger 매칭) |
| `send_hour=14, send_minute=0` | ❌ cron sweep 윈도우 (08:00~09:50) 밖. workflow 파일 cron 추가 변경 필요 |
| `send_hour=24` (잘못) | admin POST 시 400 reject |

지금 진행할 필요는 없습니다. 필요하면 ralph-loop 또는 `/fast-tasks` 로 다음 batch.

---

### 12-C. 🔥 NEXT 세션 — 옵션 A: 자동 path 추천 (admin Sources)

**왜 필요한가** (2026-05-25 2회차 운영 사고):

대표님이 14 매체 active 등록했지만 메일 결과가 Anthropic 1개 매체로 92% 쏠림. 원인 진단 (search.py 디버그 로깅, commit `0e91d83`):

```
INFO Brave RAW [OpenAI] 20 items | openai.com=13   ← Brave 는 결과 반환 OK
INFO   └ path_mismatch openai.com (3): paths=['/index/openai-on-aws/', ...]
INFO search keyword='OpenAI' → 0 results            ← 우리 코드가 다 잘림
```

즉 **Brave 는 정상 결과 반환** 하는데 **사용자 등록 path (`/news`) 와 실제 글 URL path (`/index/<slug>`) 가 안 맞아서** 100% 잘림.

| 매체 | 사용자 직관 path | **실제 글 URL path (Brave 색인)** |
|------|----------------|----------------------------------|
| OpenAI | `/news` (목록 페이지) | `/index/<slug>/` |
| Google Blog | `/technology/ai` (카테고리) | `/innovation-and-ai/...`, `/products-and-platforms/...` |
| DeepMind | `/discover/blog` | `/blog/<slug>` 또는 `/models/<slug>` |
| Microsoft | `/en-us/research/blog` | `/en-us/security/blog/...`, `/en-us/research/...` 다양 |
| Anthropic | `/news` | `/news/<slug>` ✅ (우연 일치) |
| Hugging Face | `/blog` | `/blog/<slug>` ✅ (우연 일치) |

→ "목록 페이지" 와 "글 페이지" URL 패턴이 다른 매체가 다수. 사용자는 직관적으로 목록 URL 입력하지만 Brave 는 글 URL 색인.

**해결 방향 — 옵션 A (자동 path 추천)**:

admin 이 매체 등록 시 Brave 1회 호출 → 결과 path frequency 분석 → 가장 빈번한 prefix 추천. 사용자는 도메인만 알면 OK.

**작동 흐름**:

1. 사용자가 admin Sources 추가 폼에 도메인만 입력 (예: `openai.com`)
2. "**🔍 자동 path 검출**" 버튼 클릭
3. admin 백엔드:
   - Brave Search 호출 (기본 키워드 = active 키워드 중 첫 번째, 또는 "AI" default)
   - `site:openai.com freshness:pm count:20` 등
   - 응답 URL 들의 path prefix frequency 분석:
     - `/index/...` 13건 → 추천 1순위
     - `/research/...` 3건 → 추천 2순위
4. admin UI 가 추천 결과 카드로 표시:
   ```
   openai.com 에서 발견된 글 path 패턴:
   ┌────────────────────────────────────┐
   │ ⭐ /index    (13건, 65%)  [선택]    │
   │   /research  (3건,  15%) [선택]    │
   │   /blog      (2건,  10%) [선택]    │
   │   path 없이 호스트 전체     [선택]   │
   └────────────────────────────────────┘
   ```
5. 사용자가 1개 또는 다중 선택 → 각 선택마다 `source_entries` row 추가
6. 저장 후 확인 메시지 ("openai.com/index 등록 완료. 다음 발송 시 매칭 보장")

**구현 task 추정** (1 PRD 사이클):

1. **마이그레이션 0006** — `search_sources` 에 `last_path_suggestions jsonb` 컬럼 (선택, 검출 결과 캐시)
2. **`search.py` helper** — `discover_paths(host, keyword, api_key)` 함수. Brave 호출 + path frequency 집계 + top N prefix 반환
3. **admin.py 새 라우트** — `POST /admin/sources/discover-paths` (body: domain, optional keyword). discover_paths 호출 결과 JSON 반환
4. **`templates/admin.html`** — Sources 추가 폼 옆 "🔍 자동 검출" 버튼 + 결과 카드 modal/dropdown
5. **테스트** — discover_paths 단위 (FakeBraveSession) + admin POST 통합 + AC-1..4 end-to-end

**다음 세션 시작 시점**:
- 새 PRD 폴더: `docs/features/2026-05-26-source-auto-path-suggest/`
- `/js-super:brainstorming` 또는 메인 직접 진행 (옵션 1 PRD 흐름)

**임시 대응** (옵션 A 완성 전 운영):
- admin Sources 에서 path 다 제거 → 호스트만 등록 (예: `openai.com`)
- 휴리스틱 (`_looks_like_article_url`) 이 카테고리/제품/홈 페이지 자동 차단
- 2026-05-25 commit `0bb7d86` 으로 휴리스틱 완화 (`/index`, `/blog` 등 일반 글 path 더 통과). 운영 가능

**기대 효과**:
- 사용자 시행착오 0 — 도메인만 입력
- 정확도 자동 보장 — Brave 실제 색인 path 기반
- 매체 다양성 확보 — 14 매체 × cap 3 = 매체별 균형 분포

이게 옵션 A 의 핵심. 다음 세션 첫 task.

---

### 12-A. ✅ 매체 path-prefix 필터 — 완료 (2026-05-24)

**완료 commits**: T1 (`0117a93`) / T2 (`9949b86`) / T3 (`edfc65b`) / T4 (`e292b55`) / T5 (`a54d140`) / T6 (`7fababb`) / T7 (`5667cf8`) / T8 (`680eb1a`) / log (`0f280f3`).

**최종 형태** (실제 채택은 옵션 A = 단일 컬럼. 원래 plan 의 옵션 B 컬럼 분리는 admin UX + 마이그레이션 비용 고려해 reject):
- admin Sources 입력 칸 1개. `openai.com` 또는 `openai.com/research/papers` 둘 다 OK
- `search_config_store._split_host_path()` 가 host/path 분리, `_matches_path_prefix()` 가 segment-aware (`/research` ↔ `/researchers` false positive 차단)
- `LoadedConfig.source_entries: list[SourceEntry]` 로 명시 분해. D5 (host-only 우선) 정책은 `source_name_map` 의 2-pass + `search()` 의 host_only 분기로 결정적
- search 인자는 `list[str]` / `list[SourceEntry]` 둘 다 받음 (backwards compat 보존)
- 마이그레이션 0004 불필요 — `search_sources.domain` 단일 컬럼 유지
- 자세한 변경이력: `docs/features/2026-05-24-search-path-prefix/` 의 PRD (CH-001) → tech-design (CH-002) → plan (CH-003) → 구현 batch (CH-004) → 검증 (CH-005)

**활용 예** (admin Sources 에 등록):

| 입력값 | 동작 |
|--------|------|
| `openai.com` | openai.com 전체 통과 (기존 동작) |
| `openai.com/research` | openai.com/research/... 만 통과 |
| `openai.com/research` + `openai.com/news` (두 row) | 두 prefix 모두 통과 |
| `openai.com` + `openai.com/research` (두 row 공존) | host-only 우선 → 전체 통과 (D5) |
| `https://openai.com` | 400 reject (스킴 거부) |

**아래는 원래 본 섹션의 구현 계획 — 이력 보존용 (실제 채택은 위와 다름)**:

**왜 필요한가** (대표님 원문):
> "다음 고도화는 그 연산자도 언젠간 되게끔하는거야. 좁히지 않으니까 내가 원하는 분야가 잘 안 잡히네."

현재 `search_sources` 는 호스트만 받는다 — 매체 한 곳 전체에서 검색되므로 마케팅·이벤트·HR 글 등 잡음이 섞임. 대표님이 admin 에 `openai.com/research` 를 넣었던 의도가 이거였음.

**왜 즉시 path 를 다시 못 받게 했는가**: Brave Search `site:` 연산자는 호스트만 받음 (구글도 동일 표준). 직접 통과 → 422. 그래서 commit `7d85e69` 에서 입력 단계 reject 로 막아 뒀음. ⚠️ **이건 임시 안전장치**.

**구현 방향 (이전 대화에서 합의된 옵션 B = 클라이언트 측 필터)**:

1. **마이그레이션 0004** — `search_sources` 에 `path_prefix text` 컬럼 추가. `(domain, path_prefix) unique` 제약으로 같은 호스트 + 다른 prefix 를 별도 row 로 관리.
2. **`SourceRecord`** 에 `path_prefix: str | None` 필드 추가. `_normalize_path_prefix()` 헬퍼 — `/research` 같은 path 만 허용, 호스트/스킴/쿼리 거부.
3. **`SourceStore.add/update`** — `path_prefix` 인자 추가. 기존 None 인 row 는 그대로 동작 (backwards compatible — DB 정책 X, 코드만).
4. **`search.py`**:
   - `search()` 가 `source_domains` 대신 `list[tuple[str, str | None]]` 받도록 변경 (host, path_prefix)
   - Brave 쿼리는 여전히 `site:host` 만 (422 회피)
   - 응답 받은 후 `_looks_like_article_url` 다음 단계로 **path-prefix 매칭** 검사 추가. 매체별로 prefix 가 있는 row 가 있으면 매칭, 없으면 호스트 전체 통과.
5. **`admin.html` Sources 폼** — "경로 (선택)" 인풋 추가 + 안내 텍스트 갱신. add + edit 둘 다.
6. **테스트** — `_normalize_path_prefix` 단위 + `search` 의 prefix 필터링 통합.
7. **마이그레이션 후 DB 정리** — 기존 row 의 `path_prefix=NULL` 로 두고, 대표님이 원하는 매체만 path 추가.

**작업량 견적**: 마이그레이션 1 + store 갱신 + admin 폼 + search 필터 = **5~8 commit** 분량.

**시작 시점**: 현재 host-only 로 운영 시작 → 1~2주 안에 "이 매체는 분야 좁히고 싶다" 가 명확해질 때 시작 (그래야 어느 매체에 어떤 prefix 가 필요한지 데이터로 결정 가능). ralph-loop 또는 `/auto-brainstorm` 로 진입.

---

## 13. 의사 결정 기록 (왜 이렇게 했는지)

| 결정 | 이유 |
|------|------|
| SSR (FastAPI + Jinja2) 채택, SPA X | 대표님 1명 운영 / 폼 위주 / 빌드 시스템 X / 단일 프로세스 |
| 검색엔진 Brave > Google CSE | Google 신규 프로젝트 PERMISSION_DENIED + 발급 복잡 |
| LLM Gemini > Claude/GPT | Google AI Studio 무료 tier 가 가장 넉넉 + 한국어 품질 |
| schema=ai_news 격리 | 같은 Supabase 프로젝트에 다른 서비스 들어와도 충돌 0 |
| yaml seed + DB source of truth | 도메인 재사용 (`domains/<name>/`) + admin 운영성 동시 충족 |
| BackgroundTasks 비동기 발송 | 강제발송 클릭 후 페이지 안 멈춤 + polling 으로 진행 표시 |
| ADMIN_AUTH_ENABLED=false (로컬) | 1인 운영 / 외부 노출 X / 매번 비밀번호 입력 번거로움 |
| dry-run 시 articles DB skip | 검증 환경이 운영 dedup 을 가리지 않도록 |
| search_sources 호스트만 강제 (commit `7d85e69`) → path 도 허용으로 확장 (2026-05-24 T1~T8) | 1차: Brave site: 가 path 거부 (422) — 임시 안전장치로 reject. 2차: 단일 입력 칸 + 클라이언트 측 segment-aware 필터로 정식화. 마이그레이션 0 (단일 domain 컬럼 유지) + admin UX 단순성 보존. |
| path-prefix 데이터 모델: 단일 컬럼 (옵션 A) | 옵션 B (path_prefix 분리 컬럼) 대비 admin UX 단순 (인풋 1개 유지), 마이그레이션 0, CLAUDE.md §5 "최소 UI" 원칙 부합. 단점 (컬럼 의미 약간 모호) 은 코드 주석 + _split_host_path 헬퍼로 흡수. |
| path 매칭: segment-aware (옵션 B) | 단순 startswith 는 `/research` ↔ `/researchers` false positive. segment boundary 확인이 1줄 추가로 끝나는데 정확도 큰 차이. |
| search() backwards compat (list[str] 도 허용) | 시그니처 변경 영향 최소화 + caller wave commit (T5) 의 fixture 마이그레이션 비용 ↓. 점진적 마이그레이션 가능. |
| admin-send-schedule: search_settings 확장 (vs 새 send_schedule 테이블) | ALTER TABLE 2 컬럼이 새 테이블 + RLS + store 분리보다 훨씬 가벼움. CLAUDE.md §6 6곳 갱신 룰 자연스럽게. 의미 분리 약함은 컬럼 comment 로 흡수. |
| admin-send-schedule: cron 윈도우 `*/5 23,0` (vs 하루 종일 매 5분) | 하루 종일 = 일 144회 → 월 4,320분 (free cap 2,000 초과). 비전 §4 "08:40 ±30분" 안만 sweep 으로 충분. 후속 시각 확장 필요 시 cron 표현식 추가 변경. |
| admin-send-schedule: cli.run_command 게이트 위치 (vs pipeline.run 안) | run_store.start_run 호출 전이라 skip 시 runs 테이블 깨끗. force/dry_run bypass 분기도 깔끔. |
| admin-send-schedule: has_success_today() DB query (vs in-memory / lock file) | cron runner 가 stateless 라 in-memory 무효. 단일 source 는 runs 테이블만. 1 SELECT/run 비용 무시 가능. |
| admin-send-schedule: KST explicit conversion (vs server TZ 의존) | GitHub Actions runner=UTC 고정. 로컬 개발은 환경별 발산. `ZoneInfo("Asia/Seoul")` 명시로 환경 독립. |
| T11: cron 매 10분 → 매 5분 + 윈도우 ±5분 → ±2분 (commit `d053709`) | 매 5분 + ±2분 = 한 cycle 에 1 trigger 매칭 → 발송 시각 정확도 ±2분 (매 10분 + ±5분 보다 정확). free tier 18% → 36%, 마진 64% 유지. |
| T13: 스마트 권장값 카드 (commit `5628b15`) | active 키워드/소스 수 기반 자동 계산 → 사용자 시행착오 ↓. AI 분석 기사 개수 = max(20, kw×5+10), freshness 는 total = kw×src 분기 (pd/pw/pm). |
| T13.1: 권장 공식 ×1.5 → /2 fix (commit `8a39de4`) | 14 매체에서 ×1.5 → cap 9 → 한 매체 결과 다 통과 = cap 무력. /2 로 변경 → cap 3 → 분산 강제. clamp 2..5. |
| T14: per-source cap (commit `a450002`) | 한 매체 SEO 편향 자동 방지 — 본문 추출 후 매체별 그룹화 cap. 마이그레이션 0005. 기존 max_articles_for_summary cap 과 같이 작동. 본문 추출 통과 수 (extracted_count) 는 cap 전 의미 유지. |
| T15: `_looks_like_article_url` 휴리스틱 완화 (commit `0bb7d86`) | `_MIN_LAST_SEGMENT_LEN` 10 → 5. 운영 로그에서 정상 글 다수 차단 (ai.meta=3, nvidia=5 등). `_BLOCKED_PRODUCT_SEGMENTS` 신규 — `/product`, `/events`, `/careers` 등 첫 segment 차단으로 product 페이지는 별도 제어. |
| 디버그 로깅 (commits `44de4a8`, `0e91d83`) | 사용자 운영 사고 (Anthropic 편향) 진단을 위해 pipeline + search 단계별 reject 카운트 영구 추가. `Brave RAW`, `unknown_host`, `non_article`, `path_mismatch` 4 단계 분리. 진단 비용 0, 운영 가시성 ↑. |
| 서비스명 generic 화 (commit `888c099`) | "ai_news_scraping" → "뉴스 스크래핑" 사용자 향 표기만 변경. 코드 패키지명 / DB schema 는 그대로 (운영 안전성 우선). |
| 옵션 A (자동 path 추천) NEXT 세션 결정 | 사용자가 path 정확히 알기 어려운 본질 문제 인지. 운영 측 (path 호스트만 등록) 또는 코드 측 (자동 추천) 중 후자 채택. 사용자 시행착오 0 + 정확도 자동. |

---

## 14. 연락처 / 마지막 메모

- **owner**: 대표님 (`dlwlstjq410@gmail.com`)
- **repo**: `github.com/LonerStayle/news_scraping`
- **개발 도구**: Claude Code + ralph-loop 플러그인 + js-super skills (PRD → tech-design → plan → execute-plan 자동화 흐름)
- **개발 기간**: 2026-05-23 하루 (vision-intake → Phase A~G + fast-tasks) + 2026-05-24 (search-path-prefix) + 2026-05-25 (admin-send-schedule, brand, cron tuning, per-source cap, 권장값 카드, 휴리스틱 완화 — 2회차)
- **총 commit 수**: 70+ (linear history, main 브랜치)
- **다음 세션 첫 task**: §12-C — 옵션 A (자동 path 추천). PRD 흐름 권장 (search-path-prefix 와 동일 패턴).

ralph 자동 루프로 진행됐기 때문에 모든 commit 메시지가 task 단위로 명확합니다 — `git log --oneline` 으로 진행 history 확인 가능.

질문 생기면 `CLAUDE.md` (비전·정책) → `README.md` (운영) → `architecture.html` (구조) → `setup-guide.html` (셋업) → `docs/features/<date>-<slug>/` (피처별 PRD/design/plan) 순으로 참조.

좋은 운영 되시길!
