# 요구사항: admin 발송 시각 설정 (admin-send-schedule)

> **다음 단계 안내**: 이 문서는 PRD 입니다 (비전 / FR / NFR / AC). 다음 단계 `admin-send-schedule-tech-design.md` (아키텍처 / 컴포넌트 / 결정 + 대안) 의 입력이 됩니다.

## 1. 비전

GitHub Actions cron 을 워크플로 파일 hardcode 시각 (현재 23:40 UTC) 에서 해방시켜 **admin 페이지에서 발송 시각 (HH:MM, KST 기준) 을 직접 설정 가능하게 한다.** 휴가·운영 변경·시간대 조정 시 workflow 파일 수정 / git commit 불필요. cron 은 매 10분 trigger 윈도우로 변경하고 runner 가 admin DB 의 시각과 매칭 시점에만 파이프라인을 실행.

> 대표님 원문: *"이 시간도 어드민에서 내가 정할 수 있으면 좋겠어"*

## 2. 영향 컴포넌트 (preliminary survey)

| 영역 | 파일 |
|------|------|
| 마이그레이션 | `supabase/migrations/0004_send_schedule.sql` (신규) |
| Store | `src/ai_news_scraping/search_config_store.py` (`SearchSettings` 확장) |
| Loader | `src/ai_news_scraping/search_config_loader.py` (`LoadedConfig` / 기본값) |
| 시각 게이트 | `src/ai_news_scraping/cli.py` (`run_command()`) |
| 중복 방지 | `src/ai_news_scraping/run_store.py` (`has_success_today()` helper) |
| admin 라우트 | `src/ai_news_scraping/admin.py` (`POST /admin/settings` 확장) |
| admin 폼 | `templates/admin.html` (Settings 탭 입력 2칸) |
| cron | `.github/workflows/daily-digest.yml` (윈도우 trigger) |
| 테스트 | `tests/test_search_config_store.py`, `tests/test_cli.py`, `tests/test_run_store.py` |

## 3. 기능 요구사항 (FR)

- **FR-1 (admin 입력)**: admin Settings 탭에 `send_hour` (0-23) + `send_minute` (0-59) 입력 2칸 추가. 기본값 8:40 KST. invalid 입력 (`-1`, `24`, `60` 등) 시 400.
- **FR-2 (DB 저장)**: `ai_news.search_settings` 싱글톤 row 에 `send_hour int` + `send_minute int` 컬럼 추가. 마이그레이션 시 기본값 (8, 40) 채움.
- **FR-3 (cron 변경)**: `.github/workflows/daily-digest.yml` 의 cron 을 `'*/10 23,0 * * *'` UTC 로 변경 (= KST 08:00, 08:10, …, 09:50 매 10분, 일 12회).
- **FR-4 (시각 게이트)**: `cli.run_command()` 가 파이프라인 진입 전 다음 순서로 게이트 체크:
  1. `force=False` (cron 자동 실행) 이고 `dry_run=False` 일 때만 적용
  2. admin DB 에서 `(send_hour, send_minute)` 로드
  3. 현재 KST 시각 (`datetime.now(KST)`) 과 매칭: `|now - target| ≤ window_minutes` (window=5분 고정)
  4. 윈도우 밖이면 즉시 return (logging: `"send-schedule gate: outside window, skipping"`), runs 테이블에 row 추가 X
- **FR-5 (중복 방지)**: 같은 날 (KST 자정 기준) `status=success` 인 run 이 존재하면 skip. `run_store.has_success_today()` helper 사용. logging: `"send-schedule gate: already sent today (run=<uuid>), skipping"`.
- **FR-6 (강제발송 무시)**: `force=True` (admin "▶ 강제발송" 버튼) 는 시각 게이트 / 중복 방지 모두 무시 (기존 동작 보존).
- **FR-7 (dry-run 무시)**: `dry_run=True` 는 시각 게이트 / 중복 방지 모두 무시 (로컬 테스트 용이성).
- **FR-8 (admin Overview 표시)**: admin Overview 탭에 현재 발송 시각 (`08:40 KST`) 1줄 노출 (운영 가시성).

## 4. 비기능 요구사항 (NFR)

- **NFR-1 (무료 인프라 유지)**: GitHub Actions free tier (private repo 월 2,000분) 안. 매 10분 trigger × 일 12회 × 1분/회 = **월 360분 (free tier 의 18%)**.
- **NFR-2 (시간 정확도)**: ±5분 윈도우. cron 자체의 ±15분 지연 가능성 (GitHub Actions 보장)을 흡수.
- **NFR-3 (admin UX)**: 시각 입력은 폼에서 2칸 (hour / minute) 분리. 기본값 prefill. KST 라고 명시. 잘못된 값은 클라이언트 + 서버 양쪽 검증.
- **NFR-4 (관측성)**: 게이트 skip 시 logging 으로 사유 명시 ("outside window" / "already sent today"). runs 테이블에는 row 추가 X (skip 은 운영 정상 동작).

## 5. 수용 기준 (AC)

- **AC-1 (정시 매칭)**: admin 에서 `send_hour=9, send_minute=15` 저장 후, 09:15 KST 에 trigger 된 cron run 이 파이프라인 진행 (runs 테이블에 success row 추가, 메일 발송).
- **AC-2 (윈도우 밖 skip)**: 같은 설정에서 09:00 KST 에 trigger 된 cron run 은 윈도우 (09:10~09:20) 밖이라 skip. runs 테이블에 row 추가 X. logging 만.
- **AC-3 (중복 방지)**: 같은 날 09:15 success 후 09:20 KST 에 cron 재 trigger 시 `has_success_today()` 가 True → skip.
- **AC-4 (강제발송 무시)**: `force=True` 시 시각 / 중복 게이트 모두 무시하고 진행 (시각 무관, 같은 날 두 번 발송 가능).
- **AC-5 (dry-run 무시)**: `dry_run=True` 시 시각 게이트 무시. 기존 dedup-skip 룰은 그대로.
- **AC-6 (invalid reject)**: admin POST `send_hour=24` 또는 `send_minute=60` 시 400 응답 + 폼 에러 표시. DB 갱신 X.
- **AC-7 (기본값 보존)**: 마이그레이션 0004 적용 직후 admin Settings 진입 시 `send_hour=8, send_minute=40` prefill (현재 hardcode 와 동일).

## 6. 비전과의 정합성

- CLAUDE.md §3 (4 핵심 산출물) 의 (3) "메일 발송기 — 매일 08:40 ± 30분" 에 부합. 시각은 admin 에서 변경 가능하지만 default 는 그대로 8:40 KST.
- CLAUDE.md §6 의 admin 운영 원칙 (yaml=seed, DB=source of truth) 과 동일 패턴. 발송 시각은 yaml 에 없음 → DB 가 단일 source. 마이그레이션이 기본값 (8, 40) 채움.
- CLAUDE.md §6 "검색 조건 admin 운영 원칙" 의 **6곳 갱신 룰** 그대로 적용: (a) 마이그레이션 (b) SearchSettings dataclass (c) LoadedConfig (d) PipelineParams/cli (e) admin POST (f) admin.html 폼.

## 7. 범위 밖 (out of scope)

- 시간대 (timezone) 설정 UI — KST 고정 (대표님 + 동료가 모두 한국).
- 다중 발송 시각 (예: 아침/저녁 2회) — 비전 §4 "매일 1회" 유지.
- 발송 윈도우 크기 (`window_minutes`) admin 설정 — 5분 고정 (변경 필요 시 코드 상수만 조정).
- GitHub Actions workflow 파일 자체를 admin 에서 PATCH — 거부 (PAT 권한 필요 + 매번 commit 발생). 매 10분 trigger 윈도우 방식이 무겁지 않음.
- 알람 / 발송 실패 슬랙 알림 — 비전 §5 의 "최소 UI" 정책 유지.

## 8. 위험 / 가정

- **위험 1 (cron drift)**: GitHub Actions 의 ±15분 지연이 5분 윈도우보다 크면 발송 누락. → 매 10분 trigger 가 KST 08:00~09:50 사이 12회 시도하므로 1회 누락해도 다음 10분이 또 catch. 단일 trigger 가 아니라 윈도우 sweep 이 안전망.
- **위험 2 (다중 instance race)**: 같은 10분 안에 cron 이 2번 trigger 되는 케이스 (GitHub 측 재시도). → `has_success_today()` 가 동일 트랜잭션 내 race 도 막음 (runs 테이블 unique 제약 + status 체크). 실제로는 거의 발생 X.
- **위험 3 (admin invalid)**: send_hour=null / send_minute=null 케이스. → 마이그레이션이 NOT NULL + DEFAULT 8, 40 으로 보장. admin POST 도 None 거부.
- **가정**: 대표님 + 구독자 모두 KST. 다른 시간대 사용자 없음 (비전 §2).

---

## 변경이력

### [2026-05-24 23:50] [요구사항-수정]
- **id**: CH-20260524-001
- **이유**: 신규 PRD 최초 생성 — admin-send-schedule 피처 (admin Settings 에서 발송 시각 HH:MM KST 변경, GitHub Actions cron 매 10분 trigger 윈도우 + 시각 게이트)
- **무엇이**: admin-send-schedule-requirements.md 전체 (§1~8)
- **영향범위**: 없음 (최초 생성)
