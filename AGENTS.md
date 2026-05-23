# AGENTS.md — 빌드/검증 명령

> ralph 가 매 iteration 검증에 사용하는 단일 출처.
> 60줄 이하 유지. 명령만. 도메인 설명은 specs/, 환경 컨텍스트는 CLAUDE.md.

---

## 환경 사전조건

- 운영체제: macOS / Linux (GitHub Actions ubuntu-latest)
- 런타임: Python >=3.11 (uv 가 자동 관리, 현재 .venv 는 3.12.x)
- 패키지 매니저: **uv** (>=0.9). `brew install uv` 또는 https://docs.astral.sh/uv/

---

## 셋업 (1회)

```bash
uv sync --dev
```

---

## 필수 검증 명령 (ralph 가 매 iteration commit 직전 실행)

모든 명령이 exit 0 이어야 commit 한다.

```bash
# 1) lint
uv run ruff check .

# 2) typecheck
uv run mypy

# 3) tests
uv run pytest
```

---

## 선택 검증

```bash
# 포맷 자동 정리
uv run ruff format .

# 도메인 파이프라인 dry-run (env 셋업 후)
# uv run python -m ai_news_scraping.cli run --dry-run
```

---

## 실행 (로컬 확인용)

```bash
# admin 페이지 (스크래핑 ON/OFF + 구독자 form)
# uv run python -m ai_news_scraping.cli admin --port 6661

# 수동 1회 발송 트리거 (cron 대신 직접 실행)
# uv run python -m ai_news_scraping.cli run
```
