# ai_news_scraping

매일 아침 영어권 주요 매체의 AI 관련 기사를 자동 수집·요약·한국어로 정리해 메일로 전달하는 서비스. 사용자가 아침 출근 전 5분 안에 그날의 AI 트렌드를 따라잡을 수 있게 한다.

자세한 비전은 [`CLAUDE.md`](./CLAUDE.md) 의 "비전 / 사양" 섹션 참조.

---

## 아키텍처 한눈에

```
              ┌────────────────────────────────────────┐
              │  GitHub Actions cron (매일 23:40 UTC)   │
              └──────────────────┬─────────────────────┘
                                 ▼
              ┌──────────────────────────────────────────┐
              │  python -m ai_news_scraping.cli run      │
              └──────────────────┬───────────────────────┘
                                 ▼
   ┌─────────────────────────────────────────────────────────┐
   │ 1) search.py      Brave Search (3위일체 검색)            │
   │    키워드 5 × 매체 10  →  site:(d1 OR d2 ...) 1 호출/kw │
   │ 2) extract.py     trafilatura 본문 추출 (실패 시 skip)  │
   │ 3) store.py       Supabase articles upsert + URL dedup  │
   │ 4) summarize.py   Gemini → 한국어 통합 트렌드 정리      │
   │ 5) mail.py        Gmail SMTP BCC 일괄 발송 (~10명)      │
   └─────────────────────────────────────────────────────────┘

   Admin (FastAPI 단일 HTML)
   ──────────────────────────
   · 자동 스크래핑 ON/OFF 토글
   · 구독자 명단 추가/제거
```

도메인 분리 가능: `domains/<name>/keywords.yaml` + `sources.yaml` 만 갈아끼우면 다른 토픽 (예: 헬스케어, 핀테크) 에 그대로 재사용.

---

## 사전 준비 (API 키 5종 발급)

모두 **무료 tier 안에서 운영** 가능합니다 (CLAUDE.md §6).

| 항목 | 발급 위치 | 비고 |
|------|----------|------|
| Brave Search API key | https://api-dashboard.search.brave.com/ → Free plan → API Keys | 월 2,000회 무료 (카드 등록 필요, 청구 0) |
| Gemini API key | https://aistudio.google.com/app/apikey | gemini-2.5-flash 무료 |
| Gmail 앱 비밀번호 | https://myaccount.google.com/apppasswords | 2FA 활성화 필요. 16자리 |
| Supabase 프로젝트 | https://supabase.com/ → 프로젝트 생성 | Free tier (Postgres 500MB) |

Admin 페이지용 임의 토큰:
```bash
openssl rand -hex 32   # 결과를 ADMIN_TOKEN 에 사용
```

---

## 로컬 셋업

요구: macOS / Linux, [uv](https://docs.astral.sh/uv/) >= 0.9.

```bash
# 1) 저장소 클론 (이미 있으면 skip)
git clone <repo-url> && cd ai_news_scraping

# 2) Python 가상환경 + 의존성 (uv 가 Python 3.12 자동 설치)
uv sync --dev

# 3) 환경변수 파일
cp .env.example .env
# .env 의 각 키를 위에서 발급한 실제 값으로 채움
```

`.env` 의 키 (자세한 설명은 `.env.example` 주석):
```
BRAVE_SEARCH_API_KEY
GEMINI_API_KEY      GEMINI_MODEL=gemini-2.5-flash
GMAIL_USER          GMAIL_APP_PASSWORD
SUPABASE_URL        SUPABASE_SERVICE_ROLE_KEY
ADMIN_TOKEN
DRY_RUN=false       DIGEST_TZ=Asia/Seoul
```

---

## Supabase 마이그레이션 적용

`supabase/migrations/0001_initial_schema.sql` 을 적용해야 합니다.

**A. Dashboard 에서 (가장 단순):**
1. https://supabase.com/dashboard → 본 프로젝트 → SQL Editor → "New query"
2. `supabase/migrations/0001_initial_schema.sql` 내용 복사 → 붙여넣기 → Run

**B. Supabase CLI 사용:**
```bash
brew install supabase/tap/supabase
supabase login
supabase link --project-ref <your-project-ref>
supabase db push
```

자세한 가이드: [`supabase/README.md`](./supabase/README.md).

---

## 로컬 dry-run

검색·추출·요약까지만 수행하고 메일 발송은 skip:
```bash
uv run python -m ai_news_scraping.cli run --dry-run
```

로그에 `status=skipped reason=dry_run` 이 찍히고, Supabase 의 `articles` 테이블에 그날 수집한 기사가 저장됩니다. Gemini 결과 자체는 메일로 보내지 않고 로그 line 에서 확인 가능.

실제 발송 (구독자 명단이 비어 있으면 skip):
```bash
uv run python -m ai_news_scraping.cli run
```

---

## GitHub Actions 배포

매일 08:40 KST (= 23:40 UTC) 자동 실행됩니다 — `.github/workflows/daily-digest.yml`.

### 1) Secrets 등록

저장소 **Settings → Secrets and variables → Actions → New repository secret** 으로 다음 8개 등록:

```
BRAVE_SEARCH_API_KEY
GEMINI_API_KEY
GMAIL_USER            GMAIL_APP_PASSWORD
SUPABASE_URL          SUPABASE_SERVICE_ROLE_KEY
ADMIN_TOKEN
```

선택 — 모델 override 가 필요하면 **Variables** 에 `GEMINI_MODEL` 추가 (기본 `gemini-2.5-flash`).

### 2) 수동 트리거로 1회 확인

Actions 탭 → "Daily AI News Digest" → "Run workflow" → `dry_run` 체크 ON → Run.

성공 후 `dry_run` OFF 로 다시 한번 실제 발송 테스트 권장.

### 3) 매일 자동 실행

이후는 cron 이 알아서 매일 08:40 KST ±30분 안에 발송. 노트북 안 켜져 있어도 동작합니다.

> ⚠️ GitHub Actions cron 은 부하 높을 때 최대 ~15분 지연 가능 — CLAUDE.md §4 의 ±30분 허용 윈도우 안.

---

## Admin 페이지

5 탭으로 운영 (Phase F):
- **Overview** — 스크래핑 ON/OFF 토글 + 전체 요약
- **Keywords** — 검색 키워드 추가/삭제/active 토글
- **Sources** — 매체 화이트리스트 (도메인 + 사람 친화명) 추가/삭제/active 토글
- **Settings** — freshness / num_results_per_keyword / max_articles_for_summary / min_body_len 운영 옵션
- **Subscribers** — 메일 명단 추가/제거

`domains/<name>/*.yaml` 은 **seed 용** — DB 가 비어 있으면 cron 첫 실행 시 yaml 에서 1회 자동 import. 이후 모든 변경은 admin 에서.

로컬 실행:
```bash
uv run python -c "
import uvicorn
from ai_news_scraping.admin import create_app
from ai_news_scraping.config import get_settings
from supabase import create_client
from ai_news_scraping.scrape_state_store import SupabaseScrapeStateStore
from ai_news_scraping.subscriber_store import SupabaseSubscriberStore
from ai_news_scraping.search_config_store import (
    SupabaseKeywordStore, SupabaseSourceStore, SupabaseSettingsStore,
)

s = get_settings()
client = create_client(s.supabase_url, s.supabase_service_role_key)
schema = s.supabase_schema
app = create_app(
    admin_token=s.admin_token,
    subscriber_store=SupabaseSubscriberStore(client, schema=schema),
    scrape_state_store=SupabaseScrapeStateStore(client, schema=schema),
    keyword_store=SupabaseKeywordStore(client, schema=schema),
    source_store=SupabaseSourceStore(client, schema=schema),
    settings_store=SupabaseSettingsStore(client, schema=schema),
)
uvicorn.run(app, host='127.0.0.1', port=8000)
"
```

브라우저: http://127.0.0.1:8000 → username 은 임의 / password 는 `ADMIN_TOKEN`.
URL hash 로 deep-link: `/#keywords`, `/#sources`, `/#settings`.

---

## 도메인 변경 (재사용)

이 코드베이스는 AI 뉴스만이 아니라 **다른 도메인에도 그대로 재사용** 할 수 있게 설계됐습니다 (CLAUDE.md §3.1).

새 도메인 `health_news` 추가:
```bash
mkdir -p domains/health_news
cat > domains/health_news/keywords.yaml <<'EOF'
keywords:
  - "FDA approval"
  - "clinical trial"
EOF
cat > domains/health_news/sources.yaml <<'EOF'
sources:
  - { domain: statnews.com,         name: STAT News }
  - { domain: nature.com,           name: Nature }
EOF

# 실행
uv run python -m ai_news_scraping.cli run --domain health_news --dry-run
```

---

## 테스트

```bash
uv run pytest          # 단위 + 통합 smoke
uv run ruff check .    # lint
uv run mypy            # typecheck
```

전부 exit 0 이어야 ralph 가 commit 합니다 (`AGENTS.md` 참조).

---

## 디렉토리 구조

```
ai_news_scraping/
├── .env.example               # 환경변수 키 + 발급 가이드 주석
├── .github/workflows/
│   └── daily-digest.yml       # 매일 23:40 UTC cron
├── domains/
│   └── ai_news/               # 키워드 + 매체 화이트리스트 (config)
│       ├── keywords.yaml
│       └── sources.yaml
├── src/ai_news_scraping/
│   ├── cli.py                 # python -m ai_news_scraping.cli
│   ├── config.py              # pydantic-settings env loader
│   ├── domain_config.py       # YAML 로더
│   ├── search.py              # Google CSE 3위일체
│   ├── extract.py             # trafilatura wrapper
│   ├── store.py               # ArticleStore (Supabase + InMemory)
│   ├── subscriber_store.py
│   ├── scrape_state_store.py
│   ├── summarize.py           # Gemini 한국어 통합 요약
│   ├── mail.py                # Gmail SMTP BCC
│   ├── pipeline.py            # end-to-end orchestration
│   └── admin.py               # FastAPI admin
├── supabase/migrations/
│   └── 0001_initial_schema.sql
├── templates/admin.html
├── tests/                     # 130+ tests
├── CLAUDE.md                  # 비전·사양 (동결됨)
├── PROMPT.md                  # ralph 행동 매뉴얼
├── IMPLEMENTATION_PLAN.md     # ralph 의 task 체크리스트
└── AGENTS.md                  # lint/typecheck/tests 명령
```

---

## 개발 노트

이 프로젝트는 **ralph harness (v3-classic)** 위에서 ralph 자율 루프로 구현됐습니다.

- `vision-intake` skill 이 8 질문으로 비전을 수집해 `CLAUDE.md` 에 동결
- `IMPLEMENTATION_PLAN.md` 의 Phase A~E task 를 ralph 가 매 iteration 1개씩 진행
- 매 commit 전 `AGENTS.md` 의 lint/typecheck/pytest 모두 exit 0 게이트

ralph 동작에 관심이 있으시면 `PROMPT.md` 와 `CLAUDE.md` 의 "공통" 섹션 참조.
