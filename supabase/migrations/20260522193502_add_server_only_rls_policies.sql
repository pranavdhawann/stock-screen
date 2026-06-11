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
    execute format('drop policy if exists server_only_all on public.%I', table_name);
    execute format(
      'create policy server_only_all on public.%I for all to service_role using (current_role = ''service_role'') with check (current_role = ''service_role'')',
      table_name
    );
  end loop;
end $$;
