-- Run the existing cleanup_expired_cache() housekeeping function hourly so
-- expired cache rows stop accumulating (rows from months back were observed).
-- cron.schedule() upserts by job name, so this migration is idempotent.
create extension if not exists pg_cron;

select cron.schedule(
  'cleanup-expired-cache',
  '17 * * * *',
  $$select public.cleanup_expired_cache()$$
);
