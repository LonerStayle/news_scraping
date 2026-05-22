# ai_news_scraping — ralph harness (v3-classic)

이 하네스는 js-ralph factory 의 template 에서 eject 되었다.
이 파일은 **자가완결**이다 — 부모 저장소를 참조하지 않는다.
Claude Code 가 매 세션 자동 로드하므로, ralph 의 매 iteration fresh context 에 항상 포함된다.

--- 

## 🔒 비전 인터뷰 상태 (gating)

```yaml
onboarded: false
onboarded_at: null
```

> `onboarded: false` 이면 ralph 는 매 iteration 첫 응답을 **비전 인터뷰** (`vision-intake` skill) 로 시작한다.
> 8 질문 답변 + "확정" 발화 후 vision-intake skill 이 위 값을 `true` + ISO 타임스탬프로 갱신하고 아래 "비전 / 사양" 섹션을 채운다.

---

## 비전 / 사양 (대표님 영역 — vision-intake 가 채움)

### 1. 비전
*(미입력. vision-intake skill 로 채워집니다.)*

### 2. 대상 사용자
*(미입력)*

### 3. 핵심 산출물
*(미입력)*

### 4. 성공 정의
*(미입력)*

### 5. 금지 / 범위 밖
*(미입력)*

### 6. 외부 의존
*(미입력)*

### 7. 규모·일정·비용 cap
*(미입력)*

### 8. 기술 스택
*(미입력 — 빈 채로 두면 아래 "기본 기술 스택" 디폴트가 적용됩니다)*

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
