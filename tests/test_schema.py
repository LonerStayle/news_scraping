"""Sanity check on the SQL migration file.

We don't run an actual Postgres here — we only verify the file exists and
contains the four tables CLAUDE.md §3 / IMPLEMENTATION_PLAN.md Phase A
require. Catches accidental deletions or renames.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_FILE = REPO_ROOT / "supabase" / "migrations" / "0001_initial_schema.sql"

REQUIRED_TABLES = ("articles", "subscribers", "runs", "scrape_enabled")


@pytest.fixture(scope="module")
def sql_text() -> str:
    assert MIGRATION_FILE.is_file(), f"missing migration: {MIGRATION_FILE}"
    return MIGRATION_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("table", REQUIRED_TABLES)
def test_each_required_table_is_created(sql_text: str, table: str) -> None:
    assert f"create table if not exists public.{table}" in sql_text


def test_rls_is_enabled_on_all_tables(sql_text: str) -> None:
    for table in REQUIRED_TABLES:
        pattern = rf"alter table public\.{table}\s+enable row level security"
        assert re.search(pattern, sql_text), f"RLS not enabled on {table}"


def test_scrape_enabled_seeds_singleton_row(sql_text: str) -> None:
    assert "insert into public.scrape_enabled" in sql_text
    assert "on conflict (id) do nothing" in sql_text


def test_articles_url_is_unique(sql_text: str) -> None:
    assert "url" in sql_text and "unique" in sql_text


def test_subscribers_email_is_unique(sql_text: str) -> None:
    assert "email" in sql_text and "unique" in sql_text


def test_runs_status_has_check_constraint(sql_text: str) -> None:
    assert "check (status in" in sql_text
    for state in ("running", "success", "failed", "skipped"):
        assert f"'{state}'" in sql_text
