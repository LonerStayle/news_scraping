---
commit_policy: per-task
---

# admin 발송 시각 설정 구현계획서 (admin-send-schedule)

> **다음 단계 안내**: 이 계획을 task-by-task 로 실행하려면 `executing-plans` (인라인 모드) 를 사용하세요. 각 step 은 체크박스 (`- [x]`) 형식이라 진행 상황 추적 가능.

**Goal:** GitHub Actions cron 을 매 10분 trigger 윈도우로 바꾸고 admin Settings 에서 발송 시각 (HH:MM KST) 을 직접 설정 가능하게.

**Architecture:** `cli.run_command()` 진입점에 시각 게이트 추가 — admin DB 의 `(send_hour, send_minute)` 와 현재 KST 시각을 ±5분 윈도우로 비교, `has_success_today()` 로 중복 방지. cron 은 `'*/10 23,0 * * *'` UTC = KST 08:00~09:50 매 10분 sweep.

**Tech Stack:** Python 3.12 / FastAPI / Supabase Postgres / GitHub Actions

**Spec inputs:**
- `admin-send-schedule-requirements.md` — FR-1~8, AC-1~7
- `admin-send-schedule-tech-design.md` — D1~D6 결정, R1~R5 위험

---

## 1. 단계별 작업

### Task 1: 마이그레이션 0004 — search_settings 에 발송 시각 컬럼 추가

**Files:**
- Create: `supabase/migrations/0004_send_schedule.sql`

**Model**: haiku

- [x] **Step 1: SQL 파일 작성**

```sql
alter table ai_news.search_settings
  add column send_hour smallint not null default 8 check (send_hour between 0 and 23),
  add column send_minute smallint not null default 40 check (send_minute between 0 and 59);

comment on column ai_news.search_settings.send_hour is 'GitHub Actions cron 매 10분 trigger 의 매칭 대상 시각 (KST, 0-23). admin Settings 에서 변경.';
comment on column ai_news.search_settings.send_minute is 'GitHub Actions cron 매 10분 trigger 의 매칭 대상 분 (KST, 0-59). admin Settings 에서 변경.';
```

- [x] **Step 2: commit**

```bash
git add supabase/migrations/0004_send_schedule.sql
git commit -m "T1: 마이그레이션 0004 — send_hour/send_minute 컬럼 추가"
```

---

### Task 2: SearchSettings dataclass + store 확장

**Files:**
- Modify: `src/ai_news_scraping/search_config_store.py`
- Modify: `tests/test_search_config_store.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 추가**

```python
def test_search_settings_default_send_time():
    s = SearchSettings(freshness="pd", num_results_per_keyword=10, max_articles_per_run=20, min_body_len=300)
    assert s.send_hour == 8
    assert s.send_minute == 40

def test_settings_store_persists_send_time():
    store = InMemorySettingsStore()
    store.save(SearchSettings(freshness="pd", num_results_per_keyword=10, max_articles_per_run=20, min_body_len=300, send_hour=9, send_minute=15))
    loaded = store.load()
    assert loaded.send_hour == 9 and loaded.send_minute == 15

@pytest.mark.parametrize("h,m", [(-1, 0), (24, 0), (0, -1), (0, 60), (25, 70)])
def test_validate_rejects_invalid_send_time(h, m):
    with pytest.raises(ValueError):
        _validate_settings(send_hour=h, send_minute=m)
```

- [x] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_search_config_store.py -v -k "send_time"
```

- [x] **Step 3: dataclass 확장 + validate helper**

`SearchSettings` 에 `send_hour: int = 8`, `send_minute: int = 40` 추가. `_validate_settings()` 가 `send_hour` 0-23 / `send_minute` 0-59 reject.

- [x] **Step 4: SupabaseSettingsStore.load() / save() 컬럼 추가**

SELECT 컬럼 list 에 `send_hour, send_minute` 포함. UPDATE 도 동일.

- [x] **Step 5: 테스트 통과 + 기존 회귀 0 확인**

```bash
uv run pytest tests/test_search_config_store.py -v
```

- [x] **Step 6: commit**

```bash
git add src/ai_news_scraping/search_config_store.py tests/test_search_config_store.py
git commit -m "T2: SearchSettings 에 send_hour/send_minute + 검증"
```

---

### Task 3: run_store.has_success_today() helper

**Files:**
- Modify: `src/ai_news_scraping/run_store.py`
- Modify: `tests/test_run_store.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 추가**

```python
def test_has_success_today_returns_false_when_empty():
    store = InMemoryRunStore()
    assert store.has_success_today(_kst_now()) is False

def test_has_success_today_true_when_today_success_exists():
    store = InMemoryRunStore()
    rid = store.start_run()
    store.mark_finished(rid, status="success", article_count=5, digest_text="...")
    assert store.has_success_today(_kst_now()) is True

def test_has_success_today_false_when_today_only_failed():
    store = InMemoryRunStore()
    rid = store.start_run()
    store.mark_finished(rid, status="error", article_count=0, error="boom")
    assert store.has_success_today(_kst_now()) is False

def test_has_success_today_false_when_yesterday_success():
    store = InMemoryRunStore()
    rid = store.start_run()
    store.mark_finished(rid, status="success", article_count=3, digest_text="어제")
    # 시각 조작 — yesterday success but query today
    yesterday_kst = _kst_now() + timedelta(days=1)
    assert store.has_success_today(yesterday_kst) is False
```

- [x] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_run_store.py -v -k "has_success_today"
```

- [x] **Step 3: InMemoryRunStore.has_success_today() 구현**

KST 자정 ~ 다음 KST 자정 사이 `status=='success'` 인 run 존재 여부. `now_kst: datetime` 인자 받음 (테스트 용이성).

- [x] **Step 4: SupabaseRunStore.has_success_today() 구현**

`select id from ai_news.runs where status='success' and finished_at >= <today_kst_midnight_utc> and finished_at < <tomorrow_kst_midnight_utc> limit 1`. KST 자정 ↔ UTC 변환 명시.

- [x] **Step 5: 테스트 통과**

```bash
uv run pytest tests/test_run_store.py -v
```

- [x] **Step 6: commit**

```bash
git add src/ai_news_scraping/run_store.py tests/test_run_store.py
git commit -m "T3: RunStore.has_success_today helper"
```

---

### Task 4: cli.run_command() 시각 게이트

**Files:**
- Modify: `src/ai_news_scraping/cli.py`
- Modify: `tests/test_cli.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 추가 — 6 케이스**

```python
def _fixed_kst(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 24, hour, minute, tzinfo=KST)

def test_cli_force_bypasses_send_schedule_gate(monkeypatch):
    # force=True → window/today 무시
    ...

def test_cli_dry_run_bypasses_send_schedule_gate(monkeypatch):
    # dry_run=True → window/today 무시
    ...

def test_cli_inside_window_proceeds(monkeypatch):
    # send=(9,15), now=(9,17), window=5min → 진행
    ...

def test_cli_outside_window_skips(monkeypatch):
    # send=(9,15), now=(9,00) → skip, runs 추가 X
    ...

def test_cli_already_sent_today_skips(monkeypatch):
    # send=(9,15), now=(9,15), 오늘 success 존재 → skip
    ...

def test_cli_proceeds_when_no_success_today(monkeypatch):
    # send=(9,15), now=(9,15), 오늘 success 없음 → 진행
    ...
```

- [x] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_cli.py -v -k "send_schedule"
```

- [x] **Step 3: `_should_send_now()` helper + run_command() 게이트 추가**

`cli.py` 에 다음 helper:

```python
from zoneinfo import ZoneInfo
KST = ZoneInfo("Asia/Seoul")
SEND_WINDOW_MINUTES = 5

def _should_send_now(send_hour: int, send_minute: int, now_kst: datetime) -> bool:
    target_minutes = send_hour * 60 + send_minute
    now_minutes = now_kst.hour * 60 + now_kst.minute
    return abs(now_minutes - target_minutes) <= SEND_WINDOW_MINUTES
```

`run_command()` 의 force / dry_run / subscribers / scrape_enabled 체크 사이에 시각 게이트 진입:

```python
if not force and not dry_run:
    now_kst = datetime.now(KST)
    if not _should_send_now(loaded.settings.send_hour, loaded.settings.send_minute, now_kst):
        logger.info("send-schedule gate: outside window (target=%02d:%02d KST, now=%s), skipping",
                    loaded.settings.send_hour, loaded.settings.send_minute, now_kst.strftime("%H:%M"))
        return
    if stores.run_store.has_success_today(now_kst):
        logger.info("send-schedule gate: already sent today, skipping")
        return
```

- [x] **Step 4: 테스트 통과 + 기존 cli 테스트 회귀 0 확인**

```bash
uv run pytest tests/test_cli.py -v
```

- [x] **Step 5: commit**

```bash
git add src/ai_news_scraping/cli.py tests/test_cli.py
git commit -m "T4: cli.run_command 시각 게이트 + has_success_today 체크"
```

---

### Task 5: admin POST + admin.html 폼 + Overview 표시

**Files:**
- Modify: `src/ai_news_scraping/admin.py`
- Modify: `templates/admin.html`
- Modify: `tests/test_admin.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 추가**

```python
def test_admin_post_settings_send_time_valid(test_client):
    r = test_client.post("/admin/settings", data={
        "freshness": "pd", "num_results_per_keyword": 10,
        "max_articles_per_run": 20, "min_body_len": 300,
        "send_hour": "9", "send_minute": "15",
    })
    assert r.status_code in (200, 303)
    loaded = test_client.app.state.stores.settings_store.load()
    assert loaded.send_hour == 9 and loaded.send_minute == 15

@pytest.mark.parametrize("h,m,reason", [("24", "0", "hour out"), ("0", "60", "minute out"), ("-1", "0", "neg"), ("abc", "0", "non-numeric")])
def test_admin_post_settings_invalid_send_time_400(test_client, h, m, reason):
    r = test_client.post("/admin/settings", data={
        "freshness": "pd", "num_results_per_keyword": 10,
        "max_articles_per_run": 20, "min_body_len": 300,
        "send_hour": h, "send_minute": m,
    })
    assert r.status_code == 400

def test_admin_overview_shows_send_time(test_client):
    r = test_client.get("/admin/")
    assert "08:40 KST" in r.text or "발송 시각" in r.text
```

- [x] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_admin.py -v -k "send_time or send_time_invalid or overview_shows_send_time"
```

- [x] **Step 3: admin.py POST 라우트 확장**

`POST /admin/settings` 핸들러에 `send_hour`, `send_minute` 폼 필드 받기. int 변환 + range 검증 (0-23, 0-59). invalid → 400 + 에러 메시지. valid → `SettingsStore.save()` 호출.

- [x] **Step 4: admin.html Settings 폼 + Overview 표시**

Settings 폼 (`form#settings-form`) 에 input 2칸 추가:

```html
<div class="form-row">
  <label>발송 시각 (KST)</label>
  <div class="time-inputs">
    <input type="number" name="send_hour" min="0" max="23" required value="{{ settings.send_hour }}" /> :
    <input type="number" name="send_minute" min="0" max="59" required value="{{ settings.send_minute }}" />
  </div>
  <small>GitHub Actions cron 이 매 10분 trigger 되며 이 시각 ±5분 윈도우에서만 발송됩니다.</small>
</div>
```

Overview 카드 (`section#overview`) 에 표시 1줄:

```html
<div class="kv-row">
  <span class="k">발송 시각</span>
  <span class="v">{{ "%02d:%02d"|format(settings.send_hour, settings.send_minute) }} KST</span>
</div>
```

- [x] **Step 5: 테스트 통과 + admin 회귀 0 확인**

```bash
uv run pytest tests/test_admin.py -v
```

- [x] **Step 6: commit**

```bash
git add src/ai_news_scraping/admin.py templates/admin.html tests/test_admin.py
git commit -m "T5: admin Settings 폼 + Overview 발송 시각 표시"
```

---

### Task 6: GitHub Actions cron 윈도우 변경

**Files:**
- Modify: `.github/workflows/daily-digest.yml`

**Model**: haiku

- [x] **Step 1: cron 표현식 변경**

`schedule.cron` 을 다음으로 변경:

```yaml
on:
  schedule:
    # KST 08:00~09:50 매 10분 trigger (UTC 23:00~00:50)
    # admin Settings 의 send_hour/send_minute 와 ±5분 매칭 시점에만 파이프라인 실행
    # 그 외 trigger 는 cli 의 시각 게이트가 즉시 skip
    - cron: '*/10 23,0 * * *'
  workflow_dispatch:
```

- [x] **Step 2: commit**

```bash
git add .github/workflows/daily-digest.yml
git commit -m "T6: cron 매 10분 윈도우 (KST 08:00~09:50) 로 변경"
```

---

### Task 7: AC end-to-end mock test

**Files:**
- Create: `tests/test_send_schedule_ac.py`

**Model**: sonnet

- [x] **Step 1: AC-1~7 매핑 테스트 작성**

```python
"""admin-send-schedule 피처의 AC-1..7 end-to-end 검증."""

# AC-1: 정시 매칭 → 파이프라인 진행
def test_AC1_at_target_time_pipeline_proceeds(...): ...

# AC-2: 윈도우 밖 → skip
def test_AC2_outside_window_skips(...): ...

# AC-3: 같은 날 success → skip
def test_AC3_already_sent_today_skips(...): ...

# AC-4: 강제발송 → 시각 무시
def test_AC4_force_bypasses_all_gates(...): ...

# AC-5: dry-run → 시각 무시
def test_AC5_dry_run_bypasses_gates(...): ...

# AC-6: invalid POST → 400
def test_AC6_admin_post_invalid_send_time_returns_400(...): ...

# AC-7: 마이그레이션 직후 기본값 (8, 40) prefill
def test_AC7_default_send_time_after_migration(...): ...
```

- [x] **Step 2: 테스트 실행 → 전부 PASS**

```bash
uv run pytest tests/test_send_schedule_ac.py -v
```

- [x] **Step 3: 전체 test suite 회귀 0 확인**

```bash
make check
```

- [x] **Step 4: commit**

```bash
git add tests/test_send_schedule_ac.py
git commit -m "T7: AC-1..7 end-to-end 검증"
```

---

### Task 8: 변경이력 batch entry + plan 체크박스 갱신

**Files:**
- Modify: `docs/features/2026-05-24-admin-send-schedule/admin-send-schedule-implementation-plan.md`

**Model**: haiku

- [x] **Step 1: 모든 task `[x]` 처리 + 변경이력 batch entry append**

batch entry 형태: `### [YYYY-MM-DD HH:MM] [코드-수정] (batch: tasks 1..7)` + 위험 카테고리 union (R1 breaking + R2 side-effect + R3 race) + task별 commit SHA 참조.

- [x] **Step 2: commit (log only)**

```bash
git add docs/features/2026-05-24-admin-send-schedule/admin-send-schedule-implementation-plan.md
git commit -m "[log] admin-send-schedule: tasks 1..7 batch entry"
```

---

## 2. 위험 코드 지점

- `src/ai_news_scraping/search_config_store.py:SearchSettings` — **breaking** | frozen dataclass 에 신규 필드 (send_hour, send_minute) 추가. 기본값 (8, 40) 으로 backward compat, 모든 fixture / 생성처 갱신 task 2 에 포함
- `src/ai_news_scraping/cli.py:run_command` 시각 게이트 분기 — **side-effect** | 잘못 저장된 send_hour 가 invalid 면 매일 skip 위험. admin POST + DB CHECK 양쪽 검증으로 차단
- `src/ai_news_scraping/run_store.py:has_success_today` — **race** | 같은 10분 안 cron 2회 trigger 시 race 가능. 트랜잭션 격리 + 실용상 거의 발생 X. AC-3 으로 명시 검증
- `.github/workflows/daily-digest.yml:schedule.cron` — **side-effect** | UTC 23,0 = KST 08,09 의 자정 분기. workflow 주석으로 변환 표 박음. workflow_dispatch 로 수동 1회 검증

## 3. 롤백 전략

- **Code**: T1~T7 의 commit 들 revert (8 개 SHA). HANDOFF.md 의 commit 목록 참조.
- **DB**: 마이그레이션 0004 down — `alter table ai_news.search_settings drop column send_hour, drop column send_minute;`. data loss 0 (default 값).
- **cron**: workflow 의 `'*/10 23,0 * * *'` 를 이전 `'40 23 * * *'` 으로 되돌리고 cli 시각 게이트 비활성화 환경변수 (`SEND_SCHEDULE_GATE=off`) — 단, 이건 후속 옵션. 정상 롤백은 git revert.

---

## 변경이력

### [2026-05-24 23:52] [구현계획서-수정]
- **id**: CH-20260524-003
- **이유**: 신규 구현계획서 — admin-send-schedule. 8 task (마이그레이션 / dataclass / has_success_today / cli 게이트 / admin 폼 / cron / AC / log) 분해, R1~R5 위험 매핑
- **무엇이**: admin-send-schedule-implementation-plan.md 전체 (§1~3 + frontmatter commit_policy=per-task)
- **영향범위**: 없음 (최초 생성)
- **연관 항목**: CH-20260524-001, CH-20260524-002

### [2026-05-24 24:30] [코드-수정] (batch: tasks 1..7)
- **id**: CH-20260524-004
- **이유**: admin-send-schedule 피처 구현 완료 — admin Settings 에서 발송 시각 (HH:MM KST) 변경 가능. cron 매 10분 trigger 윈도우 + cli 시각 게이트 + has_success_today 중복 방지
- **무엇이**: supabase/migrations/0004_send_schedule.sql, src/ai_news_scraping/search_config_store.py, src/ai_news_scraping/run_store.py, src/ai_news_scraping/cli.py, src/ai_news_scraping/admin.py, templates/admin.html, .github/workflows/daily-digest.yml, tests/ (test_search_config_store / test_run_store / test_cli / test_admin / test_send_schedule_ac / conftest / test_workflow)
- **영향범위**: cron trigger 빈도 ↑ (일 1 → 일 12), admin Settings 폼 확장 1 field, runs 조회 횟수 ↑ (일 12 SELECT, free tier 안), conftest 전역 fixture 도입 (다른 통합 테스트 모두 영향)
- **위험 카테고리**: breaking (SearchSettings frozen field 확장 — backward compat default 로 흡수) + side-effect (cron drift, send_hour 잘못 저장 시 매일 skip) + race (10분 안 2회 trigger 시 has_success_today 격리)
- **task별 세부 (7건)**:
  - Task 1: `supabase/migrations/0004_send_schedule.sql` — send_hour/send_minute smallint NOT NULL DEFAULT 8/40 + CHECK 0-23/0-59 (none) — commit `53f4b38`
  - Task 2: `search_config_store.py` — SearchSettings 확장 + _validate_settings_update 확장 + SupabaseSettingsStore.get/update 확장 (breaking) — commit `a979b39`
  - Task 3: `run_store.py` — _kst_day_bounds_utc + has_success_today (InMemory + Supabase) + FakeQuery gte/lt (race) — commit `bbf4f88`
  - Task 4: `cli.py` — KST/SEND_WINDOW_MINUTES 상수 + _now_kst + _is_within_send_window + run_command 게이트 + load_search_config 위치 이동 (side-effect) — commit `38b5ba3`
  - Task 5: `admin.py` POST + `admin.html` Settings 폼 입력 2칸 + Overview 행 추가 (none) — commit `c4629ee`
  - Task 6: `.github/workflows/daily-digest.yml` — cron '40 23 * * *' → '*/10 23,0 * * *' UTC + 주석 변환 표 (side-effect) — commit `dc79b24`
  - Task 7: `tests/test_send_schedule_ac.py` 신규 (9 케이스) + `tests/conftest.py` 신규 (autouse 전역 fixture) + `tests/test_workflow.py` 갱신 (none) — commit `b456013`
- **연관 commits**: `53f4b38`, `a979b39`, `bbf4f88`, `38b5ba3`, `c4629ee`, `dc79b24`, `b456013`
- **변경 전/후 코드**: 생략 — `git show <SHA>` 로 조회
- **연관 항목**: CH-20260524-001, CH-20260524-002, CH-20260524-003

### [2026-05-24 24:32] [검증] (task: Task 7 — AC end-to-end)
- **id**: CH-20260524-005
- **이유**: AC-1..7 (PRD §5) 1:1 매핑 + 전체 테스트 회귀 0 확인
- **무엇이**: tests/test_send_schedule_ac.py 9 케이스 (AC-1~7 + SEND_WINDOW_MINUTES 상수 + KST.key Asia/Seoul) + make check 전체 319 tests pass (이전 284 → 319, +35)
- **결과**: PASS — ruff/mypy/pytest 전부 exit 0
- **연관 commit**: `b456013`
- **연관 항목**: CH-20260524-004
