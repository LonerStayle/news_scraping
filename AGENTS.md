# AGENTS.md — 빌드/검증 명령

> ralph 가 매 iteration 검증에 사용하는 단일 출처.
> 60줄 이하 유지. 명령만. 도메인 설명은 specs/, 환경 컨텍스트는 CLAUDE.md.

---

## 환경 사전조건

<!-- 도메인에 맞게 채우십시오. 사용자가 직접 채우거나, ralph 첫 iteration 이 채웁니다.
     비어 있으면 ralph 의 backpressure (검증) 가 작동하지 못하므로 결국 채워져야 합니다. -->

- 운영체제:
- 런타임 버전:
- 패키지 매니저:

---

## 셋업 (1회)

```bash
# 예) uv sync && cd web && npm ci
```

---

## 필수 검증 명령 (ralph 가 매 iteration commit 직전 실행)

모든 명령이 exit 0 이어야 commit 한다.

```bash
# 1) lint
# 예) ruff check . && (cd web && npm run lint)

# 2) typecheck
# 예) mypy . && (cd web && npm run typecheck)

# 3) tests
# 예) pytest -q && (cd web && npm run test -- --run)
```

---

## 선택 검증

```bash
# 예) e2e, 빌드, 보안 스캔 등
```

---

## 실행 (로컬 확인용)

```bash
# 예) uvicorn app.main:app --reload
```
