# ai_news_scraping — ralph harness (v3-classic)

이 하네스는 js-ralph factory 의 template 에서 eject 되었다.
이 파일은 **자가완결**이다 — 부모 저장소를 참조하지 않는다.
Claude Code 가 매 세션 자동 로드하므로, ralph 의 매 iteration fresh context 에 항상 포함된다.

--- 

## 🔒 비전 인터뷰 상태 (gating)

```yaml
onboarded: true
onboarded_at: 2026-05-23T09:00:00+09:00
```

> `onboarded: false` 이면 ralph 는 매 iteration 첫 응답을 **비전 인터뷰** (`vision-intake` skill) 로 시작한다.
> 8 질문 답변 + "확정" 발화 후 vision-intake skill 이 위 값을 `true` + ISO 타임스탬프로 갱신하고 아래 "비전 / 사양" 섹션을 채운다.

---

## 비전 / 사양 (대표님 영역 — vision-intake 가 채움)

### 1. 비전

매일 아침 영어권 주요 매체의 AI 관련 기사를 자동으로 수집·요약·한국어로 정리해 메일로 전달하는 서비스. 대표님과 동료들이 아침 출근 전 5분 안에 그날의 AI 트렌드를 따라잡을 수 있게 한다.

### 2. 대상 사용자

AI 트렌드를 따라가야 하는 개발자/PM 소수 (~10명). 각자 자기 메일 주소로 동일한 일일 요약본을 받는다.

### 3. 핵심 산출물

1. **재사용 가능한 검색·수집 파이프라인** — 검색엔진 API 의 **3위일체 검색** (특정 키워드 + 최신시간순 + 특정 매체 화이트리스트) 으로 상위 노출 기사를 수집. AI 도메인 한정 RSS 크롤러가 아니라, **키워드/매체 config 만 갈아끼우면 다른 도메인에 재사용 가능한 구조** 가 핵심. 검색 결과 URL 로 들어가 본문 전체를 fetch.
2. **LLM 통합 요약·번역기** — 수집한 영문 기사들을 받아 **개별 번역이 아닌 그날의 AI 트렌드 통합 정리본 (한국어)** 을 생성. Gemini API 사용.
3. **메일 발송기** — 한국어 정리본을 ~10명 구독자에게 매일 **08:40 (±30분)** 에 자동 발송. Gmail SMTP.
4. **심플 admin 페이지 (버튼 1개)** — 자동 스크래핑 멈춤/재개 토글 버튼. (구독자 명단 관리도 같은 페이지에 단순 form 으로.)

### 4. 성공 정의

- **정량 1 (발송 시각)**: 매일 **08:40 ± 30분** 안에 메일 도착.
- **정량 2 (건수)**: 1회 발송당 다루는 기사 수 **10~20건**.
- **정성**: 대표님이 출근 전 5분 읽고 그날 AI 트렌드를 따라잡았다고 느낄 수 있을 것.

### 5. 금지 / 범위 밖

- **구독자 셀프 가입 공개 페이지** — 없음 (admin 페이지에서 명단 직접 관리). 단, 추가/제거 UI 자체는 admin 내부에 있음.
- **모바일 앱** — 없음 (메일 1채널).
- **다국어 출력** — 없음. **한국어 단일**.
- 화려한 대시보드/통계/차트 — 없음. admin 페이지는 버튼/명단 수준의 최소 UI.

> ✅ **포함되는 것 (헷갈리지 말 것)**: 본문 전문 fetch (검색 snippet 만으로는 LLM 요약 품질 부족), DB 에 기사 보존 (아카이브).

### 6. 외부 의존

| 영역 | 선택 | 비용 |
|------|------|------|
| 검색엔진 API | **Google Custom Search API** (일 100회 무료, 월 ~3,000 cap) | 무료 cap 안에서 운영 |
| 본문 fetch | **requests + trafilatura** (본문 영역 자동 추출. 매체별 selector 노가다 X). 추출 실패 매체는 화이트리스트에서 제외. JS 동적 렌더 매체만 Playwright fallback | 무료 |
| LLM | **Gemini API** (gemini-2.x flash 기본) | 무료 tier 사용 |
| 메일 | **Gmail SMTP** (앱 비밀번호 발급) | 무료 |
| 스케줄러 | **GitHub Actions cron** (정시 ± 최대 15분 지연 가능 — 발송 윈도우 안) | 무료 |
| DB | **Supabase (Postgres 무료 tier 500MB)** | 무료 |

호출량 설계: **키워드 5개 × 1 호출/일** (키워드별로 `site:(domain1 OR domain2 OR ... OR domain10)` 한 쿼리에 매체 10개 묶음) → 일 5 호출 → Google CSE 무료 cap 안에 안정적으로 들어옴.

### 7. 규모·일정·비용 cap

- **목표 완성 시점**: **기한 없음** (사람을 갈아넣지 않는다).
- **월 운영 비용 cap**: **완전 무료** — 어떤 항목이라도 유료 tier 진입 시 대표님께 보고 후 결정.
- **수집 매체 수**: 초기 **10개** (영어권 AI 매체).
- **검색 키워드 수**: **5개**.
- **1회 발송 기사 수**: 10~20건 (성공 정의와 동일).

### 8. 기술 스택

| 영역 | 선택 (factory 디폴트 override) |
|------|--------------------------------|
| Backend | **Python + uv** + FastAPI (admin 버튼·구독자 form 용. 거의 batch script 에 가까움) |
| Web Frontend | **단일 HTML 페이지 + 버튼 1개 + 명단 form** (React/Vite 오버킬 — FastAPI 가 같이 서빙) |
| Mobile App | **없음** |
| Database | **Supabase (Postgres 무료 tier)** |
| 스케줄러 | **GitHub Actions cron** (매일 08:40 KST = 23:40 UTC 트리거) |
| LLM | **Gemini API** |
| 검색 | **Google Custom Search API** |
| 메일 | **Gmail SMTP** |
| 본문 fetch | **requests + trafilatura** (필요시 Playwright fallback) |

---

## 공통 — 5 파일 (Geoffrey 정석 4 + Claude Code 자동 로드 1)

| 파일 | 무엇 | 누가 만드나 |
|------|------|------------|
| 이 `CLAUDE.md` | **비전 + 환경 컨텍스트 + 호칭 톤** (Claude Code 자동 로드) | vision-intake skill 이 자동 합성 (위 섹션) |
| `PROMPT.md` | ralph 행동 매뉴얼 (도구 중립) | factory 가 박아둠. 사용자는 `<!-- signs -->` 표지판 한 줄만 누적 |
| `AGENTS.md` | 빌드/검증 명령 (60줄 이하) | 대표님 또는 ralph 첫 iteration |
| `IMPLEMENTATION_PLAN.md` | 현재 TODO 체크리스트 | ralph 99% 자동. 사람은 빈 파일만 시작 |
| `specs/*.md` | (선택) 도메인 추가 사양 — api.md / ui.md / data.md 등 | 대표님 또는 ralph 첫 iteration |

> v2 의 11 phase / 15 페르소나 / 14 skill / gate-verify framework 는 **의도적으로 제거**됨.

---

## 공통 — 4 원칙 (Geoffrey 정석)

| # | 원칙 | 이 하네스에서 구현 |
|---|------|--------------------|
| 1 | 단일 prompt + 자기 재투입 루프 | ralph-loop 플러그인의 Stop hook 이 매 iteration 동일 prompt 를 fresh context 로 재투입 |
| 2 | 사람이 작성한 파일 spec | 이 CLAUDE.md 의 "비전 / 사양" 섹션 (vision-intake 합성 후 동결) + (선택) `specs/*` |
| 3 | fresh context 매 iteration | ralph 는 앞 iteration 을 기억 X. 상태는 git + 4 파일에만 |
| 4 | deterministic backpressure | `AGENTS.md` 의 검증 명령 (lint/typecheck/tests). LLM 채점 없음 |

---

## 공통 — 매 iteration 흐름

`/ralph-loop:ralph-loop` 시작 후 매 iteration ralph 가 자동 진행:

```
이 CLAUDE.md (자동 로드) + PROMPT.md (Read) → §1 절차 따라:
  specs/ 읽기 → AGENTS.md 읽기 → IMPLEMENTATION_PLAN.md 읽기
  → 첫 [ ] task 선택 (없으면 비전 기반 plan 보강)
  → 구현
  → AGENTS.md 검증 명령 (모두 exit 0)
  → PASS 면 commit + [ ]→[x]
  → 종료 → Stop hook 재투입
```

종료 조건:
- 모든 비전 항목이 plan 에 반영되고 전부 `[x]` → `PROJECT_DONE` 출력
- `--max-iterations` 도달
- 대표님 명시 정지

---

## 공통 — 사용자 호칭 / 톤

`PROMPT.md` 는 도구 중립이라 "사용자" 라고만 표기한다.
**이 CLAUDE.md 에서 "사용자 = 대표님" 으로 자동 치환**한다.

### 호칭
- 사용자 = **대표님 (방향 결정자)**
- 모든 응답·보고·커밋 메시지에 호칭은 "대표님" 으로 통일

### 톤
- 어투: 경어, 일관된 격식체. 반말 혼용 금지
- 길이: 응답·보고 3~5줄. 불필요한 수식어 제거
- 구조: 한 일 / 결과 / 다음 방향 분리
- 에러 메시지 그대로 노출 금지. "이런 결정이 필요합니다" 로 프레이밍
- 보고 첫 줄에 `대표님께:` prefix 권장 (필수 아님)

### 대표님 개입 시점 (2회)
1. **시작**: vision-intake 8 질문 답변 → 위 "비전 / 사양" 자동 합성 → "확정" 발화로 동결
2. **끝**: ralph 가 `PROJECT_DONE` 출력 후 결과물 검토

---

## 공통 — 기본 기술 스택 (factory 디폴트)

위 "8. 기술 스택" 에 override 명시 안 했으면 이 조합으로 진행한다.

| 영역 | 기본 |
|------|------|
| Backend | Python + uv + FastAPI + SQLAlchemy |
| Web Frontend | React (Vite + TypeScript) |
| Mobile App | Android (Kotlin, Android Studio). iOS / Flutter 의도적 포기 |
| Database | Postgres |
| 그 외 (인프라/CI/캐시) | 합리적 기본값 |

---

## 공통 — 신규 시작 체크리스트

- [ ] (1회) Claude Code 에 **ralph-loop 플러그인** 설치 — `/plugin install ralph-loop`
- [ ] `claude` 세션 열기 — ralph 가 vision-intake skill 자동 호출 (위 `onboarded: false` 트리거)
- [ ] 8 질문 답변 후 "확정" 발화 → 이 CLAUDE.md 의 "비전 / 사양" 자동 합성 + `onboarded: true`
- [ ] `AGENTS.md` 의 검증 명령 채우고 로컬에서 1회 exit 0 확인
- [ ] ralph-loop 시작:
  ```
  /ralph-loop:ralph-loop "Read PROMPT.md and follow it." --completion-promise "PROJECT_DONE" --max-iterations 150
  ```
- [ ] 첫 iteration 끝나고 `IMPLEMENTATION_PLAN.md` 에 `[ ]` 가 누적되는지 확인

---

## 공통 — 표지판

ralph 가 같은 실수를 반복하면 `PROMPT.md` 의 `<!-- signs -->` 섹션 아래에 한 줄 추가.
