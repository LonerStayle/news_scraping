-- 0002_search_admin.sql
-- 검색 조건 (키워드 / 매체 / 운영 옵션) 을 admin 페이지에서 운영 중 변경
-- 가능하게 하기 위한 3 테이블. yaml (domains/<name>/*.yaml) 은 seed 용으로
-- 유지 — pipeline 은 DB 우선, DB 비었으면 yaml fallback (Phase F).

-- ─────────────────────────────────────────────────────────────────────────
-- search_keywords — 검색 키워드 (CLAUDE.md §7: 5개 기본, admin 에서 추가/제거)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists ai_news.search_keywords (
    id          bigserial primary key,
    keyword     text        not null unique,
    active      boolean     not null default true,
    created_at  timestamptz not null default now()
);

create index if not exists search_keywords_active_idx
    on ai_news.search_keywords (active)
    where active = true;

-- ─────────────────────────────────────────────────────────────────────────
-- search_sources — 매체 화이트리스트 (CLAUDE.md §7: 10개 기본)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists ai_news.search_sources (
    id          bigserial primary key,
    domain      text        not null unique,
    name        text        not null,
    active      boolean     not null default true,
    created_at  timestamptz not null default now()
);

create index if not exists search_sources_active_idx
    on ai_news.search_sources (active)
    where active = true;

-- ─────────────────────────────────────────────────────────────────────────
-- search_settings — 운영 옵션 (싱글톤 id=1)
-- freshness / num_results / max_articles / min_body_len 을 admin 에서 조정
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists ai_news.search_settings (
    id                          int         primary key default 1,
    freshness                   text        not null default 'pw',
    num_results_per_keyword     int         not null default 20,
    max_articles_for_summary    int         not null default 20,
    min_body_len                int         not null default 300,
    updated_at                  timestamptz not null default now(),
    constraint search_settings_singleton check (id = 1),
    constraint search_settings_freshness_valid
        check (freshness in ('pd', 'pw', 'pm', 'py')),
    constraint search_settings_num_results_range
        check (num_results_per_keyword between 1 and 20),
    constraint search_settings_max_articles_range
        check (max_articles_for_summary between 1 and 100),
    constraint search_settings_min_body_range
        check (min_body_len between 50 and 5000)
);

-- seed singleton row (idempotent)
insert into ai_news.search_settings (id)
    values (1)
    on conflict (id) do nothing;

-- ─────────────────────────────────────────────────────────────────────────
-- RLS — service_role 만 우회
-- ─────────────────────────────────────────────────────────────────────────
alter table ai_news.search_keywords  enable row level security;
alter table ai_news.search_sources   enable row level security;
alter table ai_news.search_settings  enable row level security;
