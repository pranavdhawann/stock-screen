-- Accounts and per-user watchlists. Same trust model as every other table:
-- the Flask backend is the only client (service role); anon/authenticated
-- get nothing. Passwords are stored as Werkzeug PBKDF2 hashes, never plain.
create extension if not exists pgcrypto;

create table if not exists public.app_users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now(),
  last_login_at timestamptz,
  constraint app_users_email_lowercase check (email = lower(email)),
  constraint app_users_email_length check (char_length(email) between 3 and 254)
);

create table if not exists public.watchlist_items (
  user_id uuid not null references public.app_users (id) on delete cascade,
  symbol text not null,
  added_at timestamptz not null default now(),
  primary key (user_id, symbol),
  constraint watchlist_symbol_length check (char_length(symbol) between 1 and 16)
);

create index if not exists watchlist_items_user_idx
  on public.watchlist_items (user_id, added_at);

alter table public.app_users enable row level security;
alter table public.watchlist_items enable row level security;

drop policy if exists server_only_all on public.app_users;
create policy server_only_all on public.app_users
  for all to service_role
  using (current_role = 'service_role')
  with check (current_role = 'service_role');

drop policy if exists server_only_all on public.watchlist_items;
create policy server_only_all on public.watchlist_items
  for all to service_role
  using (current_role = 'service_role')
  with check (current_role = 'service_role');

revoke all on table public.app_users from public;
revoke all on table public.app_users from anon, authenticated;
revoke all on table public.watchlist_items from public;
revoke all on table public.watchlist_items from anon, authenticated;

comment on table public.app_users
  is 'Backend-managed accounts (PBKDF2 password hashes); accessed only via the Flask service role.';
comment on table public.watchlist_items
  is 'Per-user stock watchlist symbols, written by the backend service.';
