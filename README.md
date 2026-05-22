# ai_news_scraping

ralph 하네스 (v3-classic). js-ralph factory 에서 eject 됨.
Geoffrey Huntley 의 오리지널 Ralph Wiggum 패턴 + 대표님 호칭 톤.

---

## 사전 조건 (1회 설치)

Claude Code 의 **ralph-loop 플러그인** 이 활성화돼 있어야 합니다.

```bash
# Claude Code 안에서 한 번:
/plugin install ralph-loop
# 또는 plugin marketplace 카탈로그에서 'ralph-loop' 선택
```

설치 확인: `/help` → ralph-loop 의 슬래시 커맨드들이 보여야 합니다.

---

## 5 단계 빠른 시작

### 1) 새 Claude 세션

```bash
cd ~/jinsup_ralph/ai_news_scraping
claude
```

ralph 가 `CLAUDE.md` 의 `onboarded: false` 를 감지하고 `vision-intake` skill (비전 인터뷰) 을 즉시 시작합니다:
**"대표님 안녕하십니까. 8 가지 질문을 드리겠습니다."**

> ⚠️ skill 이름은 `vision-intake` 입니다 (Claude Code 빌트인 `onboarding` skill 과 충돌 회피).

### 2) vision-intake 8 질문 답변 → CLAUDE.md 의 "비전 / 사양" 자동 합성

| 질문 | 내용 |
|------|------|
| 1. 비전 | 한 줄 비전 |
| 2. 사용자 | 1~2 문장 페르소나 |
| 3. 핵심 산출물 | 1~3 가지 |
| 4. 성공 정의 | 정량 + 정성 |
| 5. 금지 / 범위 밖 | |
| 6. 외부 의존 | API / 데이터 / 입력 |
| 7. 규모·일정·비용 cap | cycles ≤ N 등 |
| 8. 기술 스택 override | 디폴트와 다르게 갈지 |

답변 후 ralph 가 `CLAUDE.md` 의 "비전 / 사양" 섹션 8 항목을 채웁니다. 검토 후 **"확정"** 발화로 `onboarded: true` + 타임스탬프 박힙니다.

### 3) `AGENTS.md` 의 검증 명령 채우기

`AGENTS.md` 에 lint / typecheck / tests 명령을 도메인에 맞게 채우고 로컬에서 1회 돌려 모두 exit 0 인지 확인하세요. 이게 ralph 의 backpressure 입니다.

### 4) ralph-loop 시작

```
/ralph-loop:ralph-loop "Read PROMPT.md and follow it." --completion-promise "PROJECT_DONE" --max-iterations 150
```

- 매 iteration ralph 가 fresh context 로 `CLAUDE.md` (자동 로드) + `PROMPT.md` (명령에 의해 Read) 를 입력으로 받습니다
- PROMPT.md §1 절차 따라 `specs/`, `AGENTS.md`, `IMPLEMENTATION_PLAN.md` 읽고 한 task 진행 → 검증 → commit → 종료
- Stop hook 이 동일 prompt 재투입

### 5) PROJECT_DONE 검토 (마지막 1회)

ralph 가 `PROJECT_DONE` 를 출력하고 종료하면 결과물을 직접 검토.

---

## 5 파일 (Geoffrey 정석 4 + Claude Code 자동 로드 1)

| 파일 | 누가 | 무엇 |
|------|------|------|
| **`CLAUDE.md`** | factory + vision-intake 자동 합성 | 비전·사양 + 환경 컨텍스트 + 호칭 톤 (Claude Code 자동 로드) |
| `PROMPT.md` | factory + 표지판 누적 | ralph 행동 매뉴얼 (도구 중립) |
| `AGENTS.md` | 대표님 또는 ralph 첫 iteration | 빌드/검증 명령 (60줄 이하) |
| `IMPLEMENTATION_PLAN.md` | ralph 99% 자동 | TODO 체크리스트 |
| `specs/*.md` | (선택) 대표님 또는 ralph 첫 iteration | 도메인 추가 사양 — api/ui/data 등 |

---

## 사람 개입 횟수

| 시점 | 내용 | 횟수 |
|------|------|------|
| vision-intake (비전 인터뷰) | 8 질문 답변 | ~8 회 |
| 동결 | "확정" 발화 → `onboarded: true` | 1 회 |
| AGENTS.md 검증 명령 채우기 | (또는 ralph 가 채워도 됨) | 0~1 회 |
| 표지판 추가 | ralph 가 실수 반복 시 PROMPT.md `<!-- signs -->` 아래 한 줄 | 0~N 회 |
| PROJECT_DONE 검토 | 결과물 확인 | 1 회 |

---

## 4 원칙 매핑

자세한 설명은 `CLAUDE.md`.

| 원칙 | 구현 |
|------|------|
| 1. 단일 prompt 자기 재투입 | ralph-loop 플러그인 (Stop hook) |
| 2. 사람이 작성한 spec | `CLAUDE.md` 의 비전/사양 섹션 + (선택) `specs/*` |
| 3. fresh context 매 iteration | ralph-loop 기본 동작 + CLAUDE.md 자동 로드 |
| 4. deterministic backpressure | `AGENTS.md` 의 lint/typecheck/tests |

---

## v2 와의 차이 (이 하네스를 처음 보시는 분께)

이전 v2 는 11 phase + 14 skill + 15 페르소나 + gate-verify framework 였습니다. self-referential 함정에 빠지는 걸 막으려는 시도였지만, ralph 의 본질 (단순/멍청/지속) 을 잃었습니다.

v3-classic 은 Geoffrey Huntley 의 오리지널 패턴 (4 파일 + bash loop) 으로 회귀했고, **Claude Code 의 CLAUDE.md 자동 로드를 활용해 비전을 CLAUDE.md 안에 단일 출처**로 둡니다 (Geoffrey 의 specs/vision.md 분리 모델 대비 더 단순). 호칭은 "대표님" 만 유지.

자세한 회귀 결정 기록은 factory 의 `HANDOFF.md` 참조.
