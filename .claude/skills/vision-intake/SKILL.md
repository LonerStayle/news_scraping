---
name: vision-intake
description: 대표님 첫 진입 시 인사 → 8 질문 비전 인터뷰 → CLAUDE.md 의 "비전 / 사양" 섹션 합성 → 동결. CLAUDE.md 의 onboarded 가 false 일 때 자동 트리거. (Claude Code 빌트인 onboarding 과 다른 별도 skill)
model: sonnet
---

# vision-intake

> v2 의 `master-spec` / `manifest` / `chunks` framework 는 폐기.
> v3-classic 정밀화: vision 은 별도 파일(`specs/vision*` 등)이 아니라 **이 하네스의 CLAUDE.md 안에 직접** 합성한다 (Claude Code 자동 로드 활용).

---

## 트리거 조건

ralph 가 매 iteration 진입 시 `CLAUDE.md` 를 자동 로드한다. 그 안 frontmatter 또는 `## 🔒 비전 인터뷰 상태` 섹션의 `onboarded` 값을 확인:

- `onboarded: false` 또는 부재 → 이 skill 호출 (인터뷰 시작)
- `onboarded: true` → 이 skill 호출하지 않음. PROMPT.md 의 매 iteration 절차로 직접 진입

---

## 1단계 — 인사

```
대표님 안녕하십니까. ralph 입니다.
프로젝트를 시작하기 전에 8가지 질문을 드리겠습니다.
답변 후 CLAUDE.md 의 "비전 / 사양" 섹션을 자동으로 채워드리겠습니다.
검토하시고 "확정" 발화 주시면 동결하고 자율 루프로 진입합니다.
```

---

## 2단계 — 8 질문 catalog

한 번에 1~2개씩 자연스러운 흐름으로 진행한다.

| # | 질문 | 기대 형식 | CLAUDE.md 의 어느 자리에 들어가나 |
|---|------|-----------|-----------------------------------|
| 1 | **비전**: 한 줄 비전은? | 1 문장 | `### 1. 비전` |
| 2 | **사용자**: 누가 사용합니까? | 1~2 문장 페르소나 | `### 2. 대상 사용자` |
| 3 | **핵심 산출물**: 반드시 만들어야 할 것 1~3가지는? | 목록 | `### 3. 핵심 산출물` |
| 4 | **성공 정의**: 정량 지표 + 정성 기준은? | 측정 가능한 수치 포함 | `### 4. 성공 정의` |
| 5 | **금지 / 범위 밖**: 절대 만들지 말아야 할 것은? | 명시적 제외 | `### 5. 금지 / 범위 밖` |
| 6 | **외부 의존**: 필요한 API / 데이터 / 입력은? | 목록 ("없음" 가능) | `### 6. 외부 의존` |
| 7 | **규모·일정·비용 cap**: 어디까지 가야 합니까? | 숫자 또는 기간 | `### 7. 규모·일정·비용 cap` |
| 8 | **기술 스택 override**: factory 디폴트 (Python+uv+FastAPI / React / Android-Kotlin / Postgres) 와 다르게 가야 합니까? | "디폴트로" 또는 구체적 override | `### 8. 기술 스택` |

---

## 3단계 — 부족 응답 처리

응답이 모호하면 **항목당 최대 2 round** 보강 질문.

- round 1: "조금 더 구체적으로 말씀해 주시겠습니까? 예) [구체 예시]"
- round 2: 마지막 확인 1회
- 그래도 불명확 → 더 묻지 말고 진행. 해당 항목 자리에 `⚠️ 확정 필요: <간단 메모>` 로 표기.

---

## 4단계 — CLAUDE.md 합성

Edit 도구로 `CLAUDE.md` 의 **"비전 / 사양 (대표님 영역 — vision-intake 가 채움)"** 섹션 아래 8개 `### N. ...` 자리의 `*(미입력...)*` 텍스트를 답변으로 갈아끼운다.

**손대지 않을 영역**:
- `## 🔒 비전 인터뷰 상태` 의 frontmatter (5단계에서 다룸)
- `## 공통 — ...` 으로 시작하는 모든 섹션 (factory 가 박은 공통 부분)

작성 후 대표님께 안내:

```
대표님, CLAUDE.md 의 "비전 / 사양" 8 항목을 채워 두었습니다.
검토 부탁드립니다.
수정 사항이 있으시면 말씀해 주시고,
괜찮으시면 "확정" / "OK" / "진행해" 중 하나로 발화 주시면 동결하고 자율 루프로 진입하겠습니다.
```

---

## 5단계 — 동결 트리거

대표님 메시지에 아래 키워드 중 하나 포함되면 즉시 동결:

- `확정`, `OK`, `ok`, `진행해`, `동결`, `frozen`

### 동결 실행 절차

1. Edit 도구로 `CLAUDE.md` 의 `## 🔒 비전 인터뷰 상태` 섹션 yaml 블록 갱신:
   ```yaml
   onboarded: true
   onboarded_at: <현재 ISO 8601>
   ```
2. 대표님께 안내:
   ```
   대표님, CLAUDE.md 가 동결되었습니다.
   이제 ralph-loop 를 시작해 주시면 자율 진행하겠습니다.

     /ralph-loop:ralph-loop "Read PROMPT.md and follow it." --completion-promise "PROJECT_DONE" --max-iterations 150

   첫 iteration 에서 AGENTS.md 검증 명령이 비어 있으면 AGENTS.md 채움부터 진행합니다.
   ```

---

## 주의

- 이 skill 은 **1회성**이다. `onboarded: true` 이후 다시 호출되면 "이미 onboarded 된 CLAUDE.md 가 있습니다" 만 출력하고 종료.
- 재인터뷰가 필요하면 대표님이 `CLAUDE.md` 의 `onboarded` 를 `false` 로 직접 토글 후 세션 재시작.
- `specs/*` 파일은 vision-intake 가 생성하지 않는다. 도메인 추가 사양 (api/ui/data 등) 이 필요하면 대표님이 동결 후 직접 추가하거나, ralph 가 첫 iteration 에서 비전 기준으로 초안 제안 가능.
- 별도 vision 파일 (예: `specs/vision*`, `master-spec*`) 또는 `manifest*` / `chunks/` / `cycles/` 는 생성하지 마라. vision 은 CLAUDE.md 가 단일 출처다.
