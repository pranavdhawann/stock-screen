-- Pro payment-link requests.
--
-- public.waitlist answered "who wants Pro eventually?" — one row per address,
-- no plan, no lifecycle. Checkout needs more: which plan was asked for, when,
-- and whether a link has been sent yet. Repeat requests are legitimate here
-- (a user may ask for monthly, then annual, or ask again after a link
-- expires), so unlike waitlist there is no unique constraint on email.
--
-- Same trust model as every other table: the Flask service role is the only
-- client; anon/authenticated get nothing.
create table if not exists public.pro_payment_requests (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  plan text not null,
  status text not null default 'requested',
  created_at timestamptz not null default now(),
  constraint pro_payment_requests_email_lowercase check (email = lower(email)),
  constraint pro_payment_requests_email_length check (char_length(email) between 3 and 254),
  constraint pro_payment_requests_plan_check check (plan in ('pro_monthly', 'pro_annual')),
  constraint pro_payment_requests_status_check check (status in ('requested', 'link_sent', 'paid', 'cancelled'))
);

-- Supports the operational query this table exists for: "what is still
-- waiting on a link, oldest first?".
create index if not exists pro_payment_requests_status_idx
  on public.pro_payment_requests (status, created_at);

create index if not exists pro_payment_requests_email_idx
  on public.pro_payment_requests (email);

alter table public.pro_payment_requests enable row level security;

drop policy if exists server_only_all on public.pro_payment_requests;
create policy server_only_all on public.pro_payment_requests
  for all to service_role
  using (current_role = 'service_role')
  with check (current_role = 'service_role');

revoke all on table public.pro_payment_requests from public;
revoke all on table public.pro_payment_requests from anon, authenticated;

comment on table public.pro_payment_requests
  is 'Requests for a Pro checkout link, written by the Flask service role only.';
