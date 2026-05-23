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
MIGRATION_FILE_2 = REPO_ROOT / "supabase" / "migrations" / "0002_search_admin.sql"
MIGRATION_FILE_3 = REPO_ROOT / "supabase" / "migrations" / "0003_source_description.sql"

REQUIRED_TABLES = ("articles", "subscribers", "runs", "scrape_enabled")
SEARCH_ADMIN_TABLES = ("search_keywords", "search_sources", "search_settings")
SCHEMA = "ai_news"


@pytest.fixture(scope="module")
def sql_text() -> str:
    assert MIGRATION_FILE.is_file(), f"missing migration: {MIGRATION_FILE}"
    return MIGRATION_FILE.read_text(encoding="utf-8").lower()


@pytest.fixture(scope="module")
def sql_text_2() -> str:
    assert MIGRATION_FILE_2.is_file(), f"missing migration: {MIGRATION_FILE_2}"
    return MIGRATION_FILE_2.read_text(encoding="utf-8").lower()


def test_schema_is_created(sql_text: str) -> None:
    assert f"create schema if not exists {SCHEMA}" in sql_text


def test_service_role_has_schema_grants(sql_text: str) -> None:
    assert f"grant usage on schema {SCHEMA}" in sql_text
    assert "service_role" in sql_text


@pytest.mark.parametrize("table", REQUIRED_TABLES)
def test_each_required_table_is_created(sql_text: str, table: str) -> None:
    assert f"create table if not exists {SCHEMA}.{table}" in sql_text


def test_rls_is_enabled_on_all_tables(sql_text: str) -> None:
    for table in REQUIRED_TABLES:
        pattern = rf"alter table {SCHEMA}\.{table}\s+enable row level security"
        assert re.search(pattern, sql_text), f"RLS not enabled on {table}"


def test_scrape_enabled_seeds_singleton_row(sql_text: str) -> None:
    assert f"insert into {SCHEMA}.scrape_enabled" in sql_text
    assert "on conflict (id) do nothing" in sql_text


def test_articles_url_is_unique(sql_text: str) -> None:
    assert "url" in sql_text and "unique" in sql_text


def test_subscribers_email_is_unique(sql_text: str) -> None:
    assert "email" in sql_text and "unique" in sql_text


def test_runs_status_has_check_constraint(sql_text: str) -> None:
    assert "check (status in" in sql_text
    for state in ("running", "success", "failed", "skipped"):
        assert f"'{state}'" in sql_text


# ─────────── 0002 search admin migration ───────────


@pytest.mark.parametrize("table", SEARCH_ADMIN_TABLES)
def test_search_admin_tables_created(sql_text_2: str, table: str) -> None:
    assert f"create table if not exists {SCHEMA}.{table}" in sql_text_2


def test_search_admin_rls_enabled(sql_text_2: str) -> None:
    for table in SEARCH_ADMIN_TABLES:
        pattern = rf"alter table {SCHEMA}\.{table}\s+enable row level security"
        assert re.search(pattern, sql_text_2), f"RLS not enabled on {table}"


def test_search_keywords_has_unique_keyword(sql_text_2: str) -> None:
    assert "keyword" in sql_text_2 and "unique" in sql_text_2


def test_search_sources_has_domain_and_name(sql_text_2: str) -> None:
    assert "domain" in sql_text_2
    assert "name" in sql_text_2


def test_search_settings_singleton_seeded(sql_text_2: str) -> None:
    assert f"insert into {SCHEMA}.search_settings" in sql_text_2
    assert "on conflict (id) do nothing" in sql_text_2


def test_search_settings_freshness_check(sql_text_2: str) -> None:
    for v in ("'pd'", "'pw'", "'pm'", "'py'"):
        assert v in sql_text_2


def test_search_settings_range_constraints(sql_text_2: str) -> None:
    assert "num_results_per_keyword between 1 and 20" in sql_text_2
    assert "max_articles_for_summary between 1 and 100" in sql_text_2
    assert "min_body_len between 50 and 5000" in sql_text_2


# ─────────── 0003 search_sources description ───────────


def test_0003_adds_description_column() -> None:
    assert MIGRATION_FILE_3.is_file()
    text = MIGRATION_FILE_3.read_text(encoding="utf-8").lower()
    assert "alter table ai_news.search_sources" in text
    assert "add column if not exists description" in text
