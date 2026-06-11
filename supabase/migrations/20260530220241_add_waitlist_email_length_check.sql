alter table public.waitlist
  add constraint waitlist_email_max_length
  check (char_length(email) <= 254)
  not valid;

alter table public.waitlist
  validate constraint waitlist_email_max_length;
