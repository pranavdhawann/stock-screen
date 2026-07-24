-- Per-account plan entitlement.
--
-- Until now "PRO" existed only as a waitlist modal: public.waitlist collected
-- addresses, but nothing in the schema could mark an account as paid, and the
-- rate limiters keyed off client IP rather than user identity. This column is
-- the missing half - app/services/http_limits.py reads it (via the session)
-- to decide whether a request is quota-exempt.
--
-- Same trust model as the rest of the schema: the Flask service role is the
-- only writer, so nothing client-side can promote an account.
alter table public.app_users
  add column if not exists plan text not null default 'free';

-- `add constraint if not exists` does not exist in Postgres, and this
-- migration must stay re-runnable alongside the rest of the directory.
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.app_users'::regclass
      and conname = 'app_users_plan_check'
  ) then
    alter table public.app_users
      add constraint app_users_plan_check check (plan in ('free', 'pro'));
  end if;
end
$$;

comment on column public.app_users.plan
  is 'Entitlement tier: free (default, rate limited) or pro (quota exempt). Written by the backend service role only.';
