-- 0004_send_schedule.sql
-- ai_news.search_settings 에 발송 시각 (KST) 2 컬럼 추가.
-- GitHub Actions cron 이 매 10분 trigger 되며 (KST 08:00~09:50), runner 가
-- 이 두 값을 읽어 현재 KST 시각과 ±5분 윈도우 매칭 시점에만 파이프라인 진행.
-- admin Settings 탭에서 변경 가능. 기본값 (8, 40) = 기존 hardcode cron 23:40 UTC.
-- Apply via Supabase Dashboard > SQL Editor (copy-paste) or `supabase db push`.

alter table ai_news.search_settings
    add column if not exists send_hour smallint not null default 8 check (send_hour between 0 and 23),
    add column if not exists send_minute smallint not null default 40 check (send_minute between 0 and 59);

comment on column ai_news.search_settings.send_hour is 'GitHub Actions cron 매 10분 trigger 의 매칭 대상 시각 (KST, 0-23). admin Settings 에서 변경.';
comment on column ai_news.search_settings.send_minute is 'GitHub Actions cron 매 10분 trigger 의 매칭 대상 분 (KST, 0-59). admin Settings 에서 변경.';
