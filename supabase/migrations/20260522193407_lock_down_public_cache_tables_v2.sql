revoke all privileges on all tables in schema public from anon, authenticated, public;
revoke all privileges on all sequences in schema public from anon, authenticated, public;

grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

update public.waitlist set email = lower(btrim(email));

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'currents_news_cache',
    'finnhub_news_cache',
    'stock_data_cache',
    'aggregated_news_cache',
    'sentiment_cache',
    'sec_filings_cache',
    'waitlist'
  ] loop
    execute format('drop policy if exists service_role_all on public.%I', table_name);
    execute format('alter table public.%I enable row level security', table_name);
    execute format('alter table public.%I force row level security', table_name);
  end loop;
end $$;

alter table public.currents_news_cache
  alter column cache_key set not null,
  alter column news_items set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.finnhub_news_cache
  alter column symbol set not null,
  alter column news_items set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.stock_data_cache
  alter column cache_key set not null,
  alter column data set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.aggregated_news_cache
  alter column symbol set not null,
  alter column news_items set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.sentiment_cache
  alter column symbol set not null,
  alter column result set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.sec_filings_cache
  alter column cache_key set not null,
  alter column data set not null,
  alter column fetched_at set not null,
  alter column expires_at set not null;

alter table public.waitlist
  alter column email set not null,
  alter column created_at set not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'currents_news_cache_key_not_blank') then
    alter table public.currents_news_cache add constraint currents_news_cache_key_not_blank check (length(btrim(cache_key)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'currents_news_cache_expiry_valid') then
    alter table public.currents_news_cache add constraint currents_news_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'finnhub_news_cache_symbol_not_blank') then
    alter table public.finnhub_news_cache add constraint finnhub_news_cache_symbol_not_blank check (length(btrim(symbol)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'finnhub_news_cache_expiry_valid') then
    alter table public.finnhub_news_cache add constraint finnhub_news_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'stock_data_cache_key_not_blank') then
    alter table public.stock_data_cache add constraint stock_data_cache_key_not_blank check (length(btrim(cache_key)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'stock_data_cache_expiry_valid') then
    alter table public.stock_data_cache add constraint stock_data_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'aggregated_news_cache_symbol_not_blank') then
    alter table public.aggregated_news_cache add constraint aggregated_news_cache_symbol_not_blank check (length(btrim(symbol)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'aggregated_news_cache_expiry_valid') then
    alter table public.aggregated_news_cache add constraint aggregated_news_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'sentiment_cache_symbol_not_blank') then
    alter table public.sentiment_cache add constraint sentiment_cache_symbol_not_blank check (length(btrim(symbol)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'sentiment_cache_expiry_valid') then
    alter table public.sentiment_cache add constraint sentiment_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'sec_filings_cache_key_not_blank') then
    alter table public.sec_filings_cache add constraint sec_filings_cache_key_not_blank check (length(btrim(cache_key)) > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'sec_filings_cache_expiry_valid') then
    alter table public.sec_filings_cache add constraint sec_filings_cache_expiry_valid check (expires_at > fetched_at);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'waitlist_email_format') then
    alter table public.waitlist add constraint waitlist_email_format check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$');
  end if;
  if not exists (select 1 from pg_constraint where conname = 'waitlist_email_lowercase') then
    alter table public.waitlist add constraint waitlist_email_lowercase check (email = lower(email));
  end if;
end $$;

drop index if exists public.idx_agg_news_symbol;
drop index if exists public.idx_finnhub_symbol;
drop index if exists public.idx_finnhub_expires;
drop index if exists public.idx_stock_data_key;
drop index if exists public.idx_stock_data_expires;
drop index if exists public.idx_sec_filings_key;
drop index if exists public.idx_sentiment_symbol;
