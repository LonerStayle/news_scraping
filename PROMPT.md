# PROMPT — ralph 행동 매뉴얼

> 이 파일은 ralph 가 매 iteration 마다 fresh context 로 받는 단 하나의 출발점이다.
> ralph 는 앞 iteration 을 기억하지 못한다. 모든 상태는 git + 아래 4 파일에만 있다.
>
> 이 파일은 도구 중립이다. 호칭/톤 같은 환경별 컨텍스트는 `CLAUDE.md` (또는 동등 파일) 가 담당한다.

---

## 1. 매 iteration 절차

```
1. git status / git log -5 로 현재 상태 파악
2. specs/ 의 모든 .md 를 읽는다 (사용자가 동결한 비전/사양)
3. AGENTS.md 를 읽는다 (빌드/검증 명령)
4. IMPLEMENTATION_PLAN.md 를 읽는다 (현재 작업 체크리스트)
5. 다음 행동을 결정한다 (아래 §2)
6. 실행
7. AGENTS.md 의 "필수 검증 명령" 을 모두 실행해서 PASS 확인
8. PASS 면 → git commit + IMPLEMENTATION_PLAN.md 의 해당 [ ]→[x] 토글
   FAIL 면 → 코드 되돌리거나 수정해서 다시 7 (commit 금지)
9. 종료. (ralph-loop 가 즉시 다음 iteration 재투입)
```

---

## 2. "다음 행동" 의사결정 트리

```
IMPLEMENTATION_PLAN.md 에 미완 [ ] task 가 있나?
  YES → 첫 번째 [ ] 를 픽. §3 으로.
  NO  → §4 (plan 보강) 으로.

모든 vision / spec 항목이 plan 에 반영되어 있고 전부 [x]?
  → "PROJECT_DONE" 보고 + 종료
  → 종료 메시지 끝줄에 정확히: PROJECT_DONE
```

> "vision / spec" 의 출처는 환경에 따라 다르다 — Claude Code 환경이면 CLAUDE.md 의 비전 섹션, Geoffrey 원조면 specs/*. 어느 쪽이든 ralph 의 fresh context 에 자동/Read 로 로드된 사양 전체를 의미.

---

## 3. 한 task 실행 규칙

- 변경 전에 먼저 codebase 를 search 한다. 이미 구현돼 있다고 가정 X, 구현 안 됐다고도 가정 X — 직접 확인.
- 독립 가능한 하위 작업은 parallel subagents 로 병렬 dispatch.
- 코드 변경은 최소 단위로.
- 테스트 자체를 약하게 만들어 통과시키는 짓 금지 (Goodhart 함정). 검증 기준이 약하다고 느끼면 AGENTS.md 에 항목 추가 후 진행.

---

## 4. plan 이 비었거나 모자랄 때 (자체 plan 보강)

- vision / spec 에서 아직 IMPLEMENTATION_PLAN.md 에 반영되지 않은 항목을 찾는다.
- 발견 시 IMPLEMENTATION_PLAN.md 끝에 `- [ ] {task 한 줄}` 추가.
- plan 이 망가졌다고 판단되면 (모순/순서꼬임) 통째 폐기하고 vision / spec 기반으로 다시 짠다 — disposable.

---

## 5. 검증 (backpressure)

- 검증은 AGENTS.md 의 명령으로만 한다. 너 스스로 채점하지 마라.
- 모든 검증 명령이 exit 0 일 때만 commit.

---

## 6. 커밋 메시지 형식

```
<task 한 줄 요약 — IMPLEMENTATION_PLAN.md 항목 그대로>

<무엇이 추가됐는지 1~2줄, 다음에 무엇을 할지 1줄>
```

---

## 7. 표지판

ralph 가 같은 실수를 반복하면 사용자가 이 섹션 끝에 한 줄을 추가한다.

<!-- signs -->
<!-- 예) "DB 마이그레이션 추가 시 항상 down 도 작성하라" -->
