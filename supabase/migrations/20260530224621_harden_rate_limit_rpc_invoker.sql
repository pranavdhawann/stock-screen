-- Keep the rate-limit RPC callable only by the server-side service role without
-- using a SECURITY DEFINER function in the exposed public schema.
grant usage on schema private to service_role;
grant select, insert, delete on table private.rate_limits to service_role;
grant usage on sequence private.rate_limits_id_seq to service_role;

alter table private.rate_limits enable row level security;

create or replace function public.consume_rate_limit(
  p_bucket text,
  p_key text,
  p_limit integer,
  p_window_seconds integer,
  p_consume boolean default true
)
returns table(allowed boolean, remaining integer, reset_at timestamptz)
language plpgsql
security invoker
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
