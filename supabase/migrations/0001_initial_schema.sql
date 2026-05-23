-- 0001_initial_schema.sql
-- ai_news_scraping initial schema (CLAUDE.md §3, IMPLEMENTATION_PLAN Phase A).
-- Apply via Supabase Dashboard > SQL Editor (copy-paste) or `supabase db push`.

-- ─────────────────────────────────────────────────────────────────────────
-- articles — 검색 + 본문 fetch 결과 보존 (CLAUDE.md §5 "DB 보존" 요구)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.articles (
    id              bigserial primary key,
    url             text        not null unique,
    title           text,
    source_domain   text        not null,
    source_name     text,
    published_at    timestamptz,
    body_text       text,
    raw_html_excerpt text,
    keyword         text,
    run_id          uuid,
    fetched_at      timestamptz not null default now()
);

create index if not exists articles_source_domain_idx
    on public.articles (source_domain);

create index if not exists articles_fetched_at_desc_idx
    on public.articles (fetched_at desc);

-- ─────────────────────────────────────────────────────────────────────────
-- subscribers — 메일 수신 명단 (~10명)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.subscribers (
    id          bigserial primary key,
    email       text        not null unique,
    active      boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists subscribers_active_idx
    on public.subscribers (active)
    where active = true;

-- ─────────────────────────────────────────────────────────────────────────
-- runs — 매일 발송 run 의 실행 로그
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.runs (
    run_id        uuid        primary key,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    article_count int         not null default 0,
    status        text        not null
                  check (status in ('running', 'success', 'failed', 'skipped')),
    error         text,
    digest_text   text
);

create index if not exists runs_started_at_desc_idx
    on public.runs (started_at desc);

-- ─────────────────────────────────────────────────────────────────────────
-- scrape_enabled — admin 페이지의 ON/OFF 토글 (싱글톤)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.scrape_enabled (
    id          int         primary key default 1,
    enabled     boolean     not null default true,
    updated_at  timestamptz not null default now(),
    constraint  scrape_enabled_singleton check (id = 1)
);

-- seed singleton row (idempotent)
insert into public.scrape_enabled (id, enabled)
    values (1, true)
    on conflict (id) do nothing;

-- ─────────────────────────────────────────────────────────────────────────
-- RLS — service_role 키만 사용. anon/authenticated 접근 차단.
-- service_role 은 자동으로 RLS 우회 권한을 가짐.
-- ─────────────────────────────────────────────────────────────────────────
alter table public.articles        enable row level security;
alter table public.subscribers     enable row level security;
alter table public.runs            enable row level security;
alter table public.scrape_enabled  enable row level security;
