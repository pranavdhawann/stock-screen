create or replace function public.cleanup_expired_cache()
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  deleted_rows integer := 0;
  table_rows integer := 0;
begin
  delete from public.stock_data_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  delete from public.aggregated_news_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  delete from public.sentiment_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  delete from public.sec_filings_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  delete from public.currents_news_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  delete from public.finnhub_news_cache where expires_at <= now();
  get diagnostics table_rows = row_count;
  deleted_rows := deleted_rows + table_rows;

  return deleted_rows;
end;
$$;

revoke execute on function public.cleanup_expired_cache() from public;
revoke execute on function public.cleanup_expired_cache() from anon, authenticated;
grant execute on function public.cleanup_expired_cache() to service_role;

comment on function public.cleanup_expired_cache()
  is 'Deletes expired rows from backend-owned public cache tables and returns the deleted row count.';
