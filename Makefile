# ai_news_scraping — make 명령 단축집
#
# 모든 명령은 uv 가상환경 안에서 실행됩니다.
# `make` 만 치면 도움말 표시.

.DEFAULT_GOAL := help
.PHONY: help sync admin run dry-run test lint typecheck check fmt clean

ADMIN_PORT ?= 6661
ADMIN_HOST ?= 127.0.0.1
DOMAIN ?= ai_news

help:  ## 사용 가능한 명령 표시
	@echo "ai_news_scraping — make 명령"
	@echo ""
	@echo "  make sync         — 의존성 설치 (uv sync --dev)"
	@echo "  make admin        — admin 웹 UI 실행 (port=$(ADMIN_PORT))"
	@echo "  make run          — 매일 발송 파이프라인 1회 실행 (실 발송)"
	@echo "  make dry-run      — 메일 발송 없이 흐름 검증"
	@echo "  make test         — pytest"
	@echo "  make lint         — ruff check"
	@echo "  make typecheck    — mypy"
	@echo "  make fmt          — ruff format (자동 정리)"
	@echo "  make check        — lint + typecheck + test 모두"
	@echo "  make clean        — __pycache__ / .ruff_cache / .mypy_cache 정리"
	@echo ""
	@echo "환경변수 override 가능: ADMIN_PORT=8080 make admin"

sync:  ## 의존성 설치
	uv sync --dev

admin:  ## admin 웹 UI 실행 (Overview / Keywords / Sources / Settings / Subscribers)
	uv run python -m ai_news_scraping.cli admin --host $(ADMIN_HOST) --port $(ADMIN_PORT)

run:  ## 발송 파이프라인 1회 실행 (실 메일 발송)
	uv run python -m ai_news_scraping.cli run --domain $(DOMAIN)

dry-run:  ## 메일 발송 없이 검색·추출·요약까지 검증
	uv run python -m ai_news_scraping.cli run --dry-run --domain $(DOMAIN)

test:  ## pytest 전체
	uv run pytest

lint:  ## ruff check
	uv run ruff check .

typecheck:  ## mypy
	uv run mypy

fmt:  ## ruff format + ruff check --fix
	uv run ruff format .
	uv run ruff check --fix .

check: lint typecheck test  ## lint + typecheck + test (commit 직전 게이트)

clean:  ## 캐시 정리
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -rf .ruff_cache .mypy_cache .pytest_cache
