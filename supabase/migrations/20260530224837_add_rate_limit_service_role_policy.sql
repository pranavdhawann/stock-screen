drop policy if exists "Service role can manage rate limit events"
  on private.rate_limits;

create policy "Service role can manage rate limit events"
  on private.rate_limits
  as permissive
  for all
  to service_role
  using (true)
  with check (true);
