-- Daily aggregated news-sentiment snapshots per symbol. Unlike the cache
-- tables this is permanent history: it powers the "sentiment score of past
-- days" timeline so old scores survive the 15-minute sentiment cache TTL.
create table if not exists public.sentiment_history (
  symbol text not null,
  day date not null,
  score numeric(6, 4) not null,
  label text not null default 'Neutral',
  confidence numeric(4, 3) not null default 0,
  news_count integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (symbol, day)
);

alter table public.sentiment_history enable row level security;

drop policy if exists server_only_all on public.sentiment_history;
create policy server_only_all on public.sentiment_history
  for all to service_role
  using (current_role = 'service_role')
  with check (current_role = 'service_role');

revoke all on table public.sentiment_history from public;
revoke all on table public.sentiment_history from anon, authenticated;

comment on table public.sentiment_history
  is 'Daily aggregated news-sentiment snapshot per symbol, written by the backend service.';
