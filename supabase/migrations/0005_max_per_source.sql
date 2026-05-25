-- 0005_max_per_source.sql
-- ai_news.search_settings 에 매체별 최대 결과 수 cap 컬럼 추가.
-- 한 매체가 SEO 강해서 Brave 결과 다 차지하는 편향을 방지.
-- pipeline 본문 추출 후 매체별 그룹화해 N 초과 결과 drop.
-- 기본값 3 (운영 보수). 14 매체 × 3 = 42 → 30~80 cap 안에 다양성 보장.
-- Apply via Supabase Dashboard > SQL Editor (copy-paste) or `supabase db push`.

alter table ai_news.search_settings
    add column if not exists max_per_source smallint not null default 3 check (max_per_source between 1 and 20);

comment on column ai_news.search_settings.max_per_source is 'pipeline 본문 추출 후 매체별 최대 결과 수 cap. 한 매체 SEO 편향 방지. admin Settings 에서 변경.';
