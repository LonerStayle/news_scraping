-- 0003_source_description.sql
-- search_sources 에 description 컬럼 추가 (admin 운영 메모용).
-- Apply via Supabase Dashboard > SQL Editor (copy-paste) or `supabase db push`.

alter table ai_news.search_sources
    add column if not exists description text;
