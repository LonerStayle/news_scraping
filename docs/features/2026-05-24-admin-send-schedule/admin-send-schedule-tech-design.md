# 개발방향: admin 발송 시각 설정 (admin-send-schedule)

> **다음 단계 안내**: 이 문서는 기술 설계서 (아키텍처 / 컴포넌트 / 데이터 / 결정 / 위험 / 테스트 전략) 입니다. `admin-send-schedule-requirements.md` (PRD) 기반, 다음 단계 `admin-send-schedule-implementation-plan.md` (TDD task 단계별 계획) 의 입력.

## 1. 아키텍처 개요

```
┌────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions cron — 변경: '*/5 23,0 * * *' UTC                     │
│  (= KST 08:00, 08:10, ..., 09:50 — 일 22회 trigger 윈도우)             │
└────────────────────────────────┬───────────────────────────────────────┘
                                 ▼
                    ┌────────────────────────────────┐
                    │  cli.run_command(force=False)  │
                    └────────────────┬───────────────┘
                                     ▼
            ┌────────────────────────────────────────────────┐
            │  [신규] 시각 게이트 — _should_send_now()        │
            │                                                 │
            │  1. force or dry_run → bypass (기존 동작)       │
            │  2. load_send_schedule(stores) → (hour, minute) │
            │  3. now_kst = datetime.now(KST)                 │
            │  4. |now - target| ≤ 5min ? 아니면 return      │
            │  5. has_success_today(run_store)? 그러면 return │
            └────────────────┬───────────────────────────────┘
                             │ pass
                             ▼
                  ┌────────────────────────┐
                  │  기존 pipeline.run()    │
                  └────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  admin Settings 탭 — POST /admin/settings                              │
│  send_hour (0-23) + send_minute (0-59) 입력 2칸 추가                   │
│  → search_config_store.SettingsStore.save(send_hour=..., send_minute=) │
└────────────────────────────────────────────────────────────────────────┘
```

핵심: cron trigger 빈도를 ↑ (일 1회 → 일 22회 매 5분), runner 가 admin DB 의 시각과 매칭될 때만 진행. workflow 파일 hardcode 시각 제거.

## 2. 영향 받는 컴포넌트/파일

| 파일 | 변경 종류 | 핵심 |
|------|-----------|------|
| `supabase/migrations/0004_send_schedule.sql` | 신규 | `search_settings` 에 `send_hour smallint NOT NULL DEFAULT 8`, `send_minute smallint NOT NULL DEFAULT 40` 컬럼 추가 (`CHECK` 제약 포함) |
| `src/ai_news_scraping/search_config_store.py` | 수정 | `SearchSettings` dataclass 에 2 필드 추가. `SupabaseSettingsStore.load()` / `save()` SELECT/UPDATE 컬럼 추가. `_validate_settings()` 로 invalid reject |
| `src/ai_news_scraping/search_config_loader.py` | 수정 | `LoadedConfig.settings` 가 이미 `SearchSettings` 를 들고 있어서 자동 흡수. 기본값 (8, 40) yaml fallback 추가 |
| `src/ai_news_scraping/cli.py` | 수정 | `run_command()` 에 시각 게이트 진입. `_should_send_now()` helper (또는 inline) — KST 변환 + 윈도우 비교 + `has_success_today` 체크 |
| `src/ai_news_scraping/run_store.py` | 수정 | `has_success_today(now_kst: datetime) -> bool` helper 추가. KST 자정 ~ 다음 KST 자정 안의 `status=success` 존재 여부 |
| `src/ai_news_scraping/admin.py` | 수정 | `POST /admin/settings` 에 `send_hour` / `send_minute` 폼 필드 처리. invalid → 400. Overview 라우트는 settings 에서 표시값 가져옴 |
| `templates/admin.html` | 수정 | Settings 탭 폼에 input 2칸 추가 (KST 명시). Overview 카드에 "오늘 발송 시각: 08:40 KST" 표시 |
| `.github/workflows/daily-digest.yml` | 수정 | `schedule.cron` 을 `'*/5 23,0 * * *'` 으로 변경 + workflow_dispatch 유지 |
| `tests/test_search_config_store.py` | 추가/수정 | dataclass 확장 + validate reject 케이스 |
| `tests/test_run_store.py` | 추가 | `has_success_today` 단위 |
| `tests/test_cli.py` | 추가/수정 | 시각 게이트 6 케이스 (window in / out / force bypass / dry-run bypass / already sent today / valid trigger) |
| `tests/test_admin.py` | 추가/수정 | POST 폼 validation + Overview 표시 |

## 3. 데이터 모델/스키마 변경

### 마이그레이션 0004_send_schedule.sql

```sql
-- ai_news.search_settings 에 발송 시각 컬럼 추가
alter table ai_news.search_settings
  add column send_hour smallint not null default 8 check (send_hour between 0 and 23),
  add column send_minute smallint not null default 40 check (send_minute between 0 and 59);

comment on column ai_news.search_settings.send_hour is 'GitHub Actions cron 매 5분 trigger 의 매칭 대상 시각 (KST, 0-23). admin Settings 에서 변경.';
comment on column ai_news.search_settings.send_minute is 'GitHub Actions cron 매 5분 trigger 의 매칭 대상 분 (KST, 0-59). admin Settings 에서 변경.';
```

> 마이그레이션 시점 기존 row (`id=1` 싱글톤) 의 `send_hour/send_minute` 은 DEFAULT (8, 40) 로 자동 채워짐 (기존 cron `23:40 UTC = 08:40 KST` 와 동일).

### SearchSettings dataclass 확장 (frozen)

```python
@dataclass(frozen=True)
class SearchSettings:
    freshness: str
    num_results_per_keyword: int
    max_articles_per_run: int
    min_body_len: int
    send_hour: int = 8      # 신규
    send_minute: int = 40   # 신규
```

기존 dataclass 가 frozen 이라 fixture / 테스트의 모든 instance 생성처 갱신. 기본값 (8, 40) 으로 backward compat 자연스럽게.

## 4. 외부 인터페이스 — N/A

내부 모듈 변경 + admin SSR 폼만. REST API / 이벤트 발행 X.

## 5. 핵심 결정 + 대안 비교

### D1: DB 위치 — `search_settings` 확장 vs 새 `send_schedule` 테이블

**채택**: `search_settings` 확장.

| 비교축 | search_settings 확장 (채택) | 새 send_schedule 테이블 |
|--------|----------------------------|-------------------------|
| 마이그레이션 | ALTER TABLE 2 컬럼 | CREATE TABLE + RLS + 시드 |
| 코드 변경 | dataclass 2 필드, store 2 컬럼 | 새 store 클래스 + loader 분리 |
| 의미 분리 | 약함 ("search 설정" 안에 발송 시각) | 깔끔 |
| 6곳 갱신 룰 | 자연스러움 (CLAUDE.md §6 패턴) | 7~8곳으로 확장 |

이유: admin Settings 탭은 이미 "운영 설정" 의 일관 surface. 의미 분리 약한 단점은 컬럼 comment + admin 폼 그룹으로 흡수 가능. 코드 변경 비용 vs 의미 분리 trade-off 에서 비용 절감 우선.

### D2: 시각 표현 — `(hour, minute)` 정수 2개 vs HH:MM 문자열 vs `time` 타입

**채택**: `(hour, minute)` 정수 2개.

| 비교축 | 정수 2개 (채택) | HH:MM 문자열 | Postgres `time` |
|--------|----------------|--------------|-----------------|
| 검증 | smallint + CHECK 단순 | regex + parse | OK |
| admin 폼 ↔ DB | HTML number input 직결 | parse 필요 | 같음 |
| 코드 가독성 | `now.hour == h and now.minute == m` 직관 | parse 후 비교 | datetime 변환 |
| 향후 확장 (window 분 단위 등) | 자연스러움 | parsing 추가 | 가능 |

이유: 모든 검증 / UI / 비교 경로가 정수 2개로 가장 단순. admin 폼 input `type="number"` 와 DB smallint 가 1:1 매핑.

### D3: cron 윈도우 범위 — KST 08:00~09:50 vs 하루 종일

**채택**: `'*/5 23,0 * * *'` UTC (= KST 08:00~09:50, 일 22회).

| 비교축 | 08:00~09:50 (채택) | 하루 종일 (*/10) |
|--------|--------------------|-----------------|
| 일 trigger 수 | 12회 | 144회 |
| 월 GitHub Actions 분 | ~360분 (free 2,000 의 36%) | ~4,320분 (free 초과) |
| 시간 변경 유연성 | KST 08~09 안만 변경 가능 | 어느 시각이든 OK |
| 비전 §4 (08:40 ±30분) 부합 | ✅ 09:50 까지 cover | 과도 |

이유: 비전 §4 의 "08:40 KST ±30분" 윈도우 안에서 어느 분이든 설정 가능. 하루 종일 trigger 는 free tier 초과 + 운영상 불필요. 향후 발송 시각을 09:50 밖으로 확장 필요 시 workflow 파일만 수정.

### D4: 시각 게이트 위치 — `cli.run_command()` vs `pipeline.run()` vs admin trigger

**채택**: `cli.run_command()` (진입점, `run_store.start_run()` 호출 전).

| 비교축 | cli (채택) | pipeline | admin |
|--------|-----------|----------|-------|
| 위치 | cron / cli 의 단일 진입점 | 너무 깊음 | admin 은 force=True 라 무관 |
| 게이트 skip 시 runs 추가 X | 자연스러움 | start_run 이후라 cleanup 필요 | N/A |
| 강제발송 호환 | force=True 분기로 bypass | 같음 | N/A |
| 테스트 격리 | helper 분리 가능 | pipeline 자체 복잡 | N/A |

이유: 시각 게이트는 "발송 진행 여부" 결정. `run_store.start_run()` 호출 전에 게이트 → skip 시 runs 테이블 깨끗. logging 만으로 충분.

### D5: 중복 방지 방식 — `has_success_today()` DB query vs in-memory cache vs lock file

**채택**: `run_store.has_success_today(now_kst)` DB query.

| 비교축 | DB query (채택) | in-memory | lock file |
|--------|----------------|-----------|-----------|
| GitHub Actions runner | OK (Supabase 호출) | 매번 새 VM 이라 무효 | 같음 |
| race 안전성 | 트랜잭션 격리 | 무관 | 무관 |
| 단일 source | runs 테이블 | 분산 | 분산 |
| 비용 | 1 SELECT/run | 0 | 0 |

이유: cron runner 는 stateless. 단일 source 는 `runs` 테이블만. 1 SELECT 추가 비용 무시 가능.

### D6: 시간대 처리 — server timezone vs explicit KST conversion

**채택**: explicit KST conversion (`zoneinfo.ZoneInfo("Asia/Seoul")`).

| 비교축 | explicit KST (채택) | server TZ |
|--------|--------------------|-----------|
| GitHub Actions runner | UTC 고정 | 의존 위험 |
| 로컬 개발 | KST 강제 | 환경별 달라짐 |
| 코드 가독성 | `now_kst = datetime.now(KST)` 명시 | 암묵 |
| 테스트 | freeze_time 또는 mock 으로 KST 명시 | 환경 의존 |

이유: KST 가 비전 §1 의 고정값. 코드 어디든 KST 변환을 명시적으로. server TZ 의존은 환경별 발산 위험.

## 6. 위험/사이드이펙트 (preliminary)

| ID | 위치 (예상) | 카테고리 | 설명 | 완화 |
|----|-------------|---------|------|------|
| R1 | `search_config_store.SearchSettings` | breaking | frozen dataclass 에 신규 필드 추가 → 모든 인스턴스 생성처 갱신 필요 | 기본값 (8, 40) 으로 backward compat. fixture / 테스트 일괄 갱신 task 분리 |
| R2 | `cli.run_command()` 시각 게이트 | side-effect | 잘못 저장된 send_hour=99 같은 invalid 가 게이트 통과 → 매일 skip | admin POST 양쪽 검증 (FR-1) + DB CHECK 제약. 잘못 저장 자체 차단 |
| R3 | `runs` 테이블 query | race | 같은 10분 안 cron 2회 trigger 시 `has_success_today` race | 트랜잭션 격리 + cron 단계에서 같은 10분에 2회 trigger 매우 드물어 실용상 무시 가능. 단, AC-3 테스트로 명시 검증 |
| R4 | cron workflow `'*/5 23,0 * * *'` | side-effect | UTC 23 = KST 08, UTC 0 = KST 09 (자정 넘어가는 분기) | cron 표현식 명시 + workflow 주석으로 KST 변환 표 박음. 검증: workflow_dispatch 로 수동 1회 |
| R5 | admin Overview 표시 | side-effect | DB 미적용 (마이그레이션 0004 안 돔) 환경에서 컬럼 부재 → SELECT 실패 | SettingsStore.load() 가 컬럼 부재 시 fallback (기본값 8, 40) 반환. 단, 운영은 마이그레이션 적용 가정 |

## 7. 테스트 전략

- **단위**: `_validate_settings()` reject 케이스 (hour=24, minute=60, type 오류), `has_success_today()` (오늘 success 있음/없음/오늘 fail 만), `SearchSettings` dataclass 기본값
- **통합 (cli 게이트)**: `run_command()` 6 케이스 — (a) force=True 무관 통과 (b) dry_run=True 무관 통과 (c) cron + window 안 통과 (d) cron + window 밖 skip (e) cron + 오늘 success 존재 skip (f) cron + invalid settings 에러 처리
- **admin**: POST `send_hour=9, send_minute=15` 성공 → DB 갱신 확인. POST `send_hour=24` → 400. Overview GET 시 표시값 확인
- **AC end-to-end**: AC-1..7 을 `tests/test_send_schedule_ac.py` 에 1:1 매핑
- 기존 tests 회귀 0 — 추가만, 변경 최소

---

## 변경이력

### [2026-05-24 23:51] [개발방향-수정]
- **id**: CH-20260524-002
- **이유**: 신규 기술 설계 — admin-send-schedule. D1~D6 (DB 위치 / 시각 표현 / cron 윈도우 / 게이트 위치 / 중복 방지 / 시간대) 결정 명시
- **무엇이**: admin-send-schedule-tech-design.md 전체 (§1~7)
- **영향범위**: 없음 (최초 생성)
- **연관 항목**: CH-20260524-001
