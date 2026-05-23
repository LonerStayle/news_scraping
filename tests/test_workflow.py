"""GitHub Actions workflow sanity checks.

YAML structure 검증은 PyYAML 의 ``on`` 키워드 해석 이슈 (1.1 spec 에서 True
로 해석) 가 있어 raw text substring 검증으로 간다. 의도 명확성과 robustness
모두 충족.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW_FILE = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-digest.yml"
)

REQUIRED_SECRETS = [
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    "GEMINI_API_KEY",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "ADMIN_TOKEN",
]


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_FILE.is_file(), f"missing workflow file: {WORKFLOW_FILE}"
    return WORKFLOW_FILE.read_text(encoding="utf-8")


def test_cron_at_2340_utc_for_0840_kst(workflow_text: str) -> None:
    assert 'cron: "40 23 * * *"' in workflow_text


def test_workflow_dispatch_with_dry_run_input(workflow_text: str) -> None:
    assert "workflow_dispatch:" in workflow_text
    assert "dry_run:" in workflow_text


@pytest.mark.parametrize("secret_key", REQUIRED_SECRETS)
def test_secret_is_wired_into_env(workflow_text: str, secret_key: str) -> None:
    assert f"{secret_key}:" in workflow_text
    assert f"secrets.{secret_key}" in workflow_text


def test_cli_run_is_invoked(workflow_text: str) -> None:
    assert "python -m ai_news_scraping.cli run" in workflow_text


def test_uv_sync_uses_frozen_lockfile(workflow_text: str) -> None:
    assert "uv sync --frozen" in workflow_text


def test_concurrency_prevents_overlap(workflow_text: str) -> None:
    assert "concurrency:" in workflow_text
    assert "group: daily-digest" in workflow_text


def test_timeout_is_set(workflow_text: str) -> None:
    # 15분 timeout (CLAUDE.md §6: GitHub Actions cron ± 최대 15분 지연 보장 안)
    assert "timeout-minutes:" in workflow_text


def test_permissions_are_read_only(workflow_text: str) -> None:
    assert "permissions:" in workflow_text
    assert "contents: read" in workflow_text
