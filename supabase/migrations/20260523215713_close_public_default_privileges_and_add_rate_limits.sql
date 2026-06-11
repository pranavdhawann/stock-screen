create schema if not exists private;

revoke all on schema private from public, anon, authenticated;
revoke all privileges on all tables in schema public from public, anon, authenticated;
revoke all privileges on all sequences in schema public from public, anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on tables from public;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from public;
alter default privileges for role postgres in schema public revoke execute on functions from anon, authenticated;
alter default privileges for role postgres in schema public revoke execute on functions from public;

do $$
begin
  begin
    alter default privileges for role supabase_admin in schema public revoke all on tables from anon, authenticated;
    alter default privileges for role supabase_admin in schema public revoke all on tables from public;
    alter default privileges for role supabase_admin in schema public revoke all on sequences from anon, authenticated;
    alter default privileges for role supabase_admin in schema public revoke all on sequences from public;
    alter default privileges for role supabase_admin in schema public revoke execute on functions from anon, authenticated;
    alter default privileges for role supabase_admin in schema public revoke execute on functions from public;
  exception
    when insufficient_privilege then
      raise warning 'Unable to change supabase_admin default privileges from the migration role. Apply these revokes from a Supabase owner/admin context.';
  end;
end $$;

create table if not exists private.rate_limits (
  id bigint generated always as identity primary key,
  bucket text not null,
  key_hash text not null,
  event_at timestamptz not null default now(),
  constraint rate_limits_bucket_not_blank check (length(btrim(bucket)) > 0),
  constraint rate_limits_key_hash_not_blank check (length(btrim(key_hash)) > 0)
);

create index if not exists rate_limits_bucket_key_event_idx
  on private.rate_limits (bucket, key_hash, event_at desc);

create or replace function public.consume_rate_limit(
  p_bucket text,
  p_key text,
  p_limit integer,
  p_window_seconds integer,
  p_consume boolean default true
)
returns table(allowed boolean, remaining integer, reset_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_window interval;
  v_count integer;
  v_oldest timestamptz;
  v_allowed boolean;
  v_remaining integer;
  v_reset_at timestamptz;
begin
  if p_bucket is null or length(pg_catalog.btrim(p_bucket)) = 0 then
    raise exception 'bucket is required';
  end if;
  if p_key is null or length(pg_catalog.btrim(p_key)) = 0 then
    raise exception 'key is required';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 10000 then
    raise exception 'invalid rate limit';
  end if;
  if p_window_seconds is null or p_window_seconds < 1 or p_window_seconds > 2678400 then
    raise exception 'invalid rate limit window';
  end if;

  v_window := pg_catalog.make_interval(secs => p_window_seconds);

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_bucket || ':' || p_key, 0)
  );

  delete from private.rate_limits
  where event_at <= v_now - v_window;

  select count(*)::integer, min(event_at)
  into v_count, v_oldest
  from private.rate_limits
  where bucket = p_bucket
    and key_hash = p_key;

  v_allowed := v_count < p_limit;

  if v_allowed and p_consume then
    insert into private.rate_limits (bucket, key_hash, event_at)
    values (p_bucket, p_key, v_now);
    v_count := v_count + 1;
    v_oldest := coalesce(v_oldest, v_now);
  end if;

  v_remaining := greatest(p_limit - v_count, 0);
  v_reset_at := coalesce(v_oldest + v_window, v_now + v_window);

  return query select v_allowed, v_remaining, v_reset_at;
end;
$$;

revoke execute on function public.consume_rate_limit(text, text, integer, integer, boolean)
  from public, anon, authenticated;
grant execute on function public.consume_rate_limit(text, text, integer, integer, boolean)
  to service_role;
