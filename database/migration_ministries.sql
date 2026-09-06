-- ============================================================
-- Add ministries as a fixed lookup table (like job_roles),
-- and wire profiles + quiz_questions to reference it.
-- ============================================================

create table ministries (
  id uuid primary key default gen_random_uuid(),
  name text not null unique
);

alter table ministries enable row level security;
create policy "Authenticated users can read ministries" on ministries for select using (auth.role() = 'authenticated');

-- profiles currently has a free-text ministry_department column.
-- Add the real FK column alongside it — don't drop the old one yet,
-- so existing rows aren't silently orphaned before you've migrated them.
alter table profiles add column if not exists ministry_id uuid references ministries(id);

-- Once your signup form's ministry field is a dropdown writing to
-- ministry_id, and you've backfilled or cleared old rows, retire the
-- free-text column:
-- alter table profiles drop column ministry_department;

-- quiz_questions gets an optional ministry_id: a question can be
-- ministry-specific (e.g. an agriculture-census scenario) or generic
-- (ministry_id left null = applies to that skill/role regardless of
-- ministry). This is what lets your generator produce different
-- phrasing per ministry without changing which skills get measured.
alter table quiz_questions add column if not exists ministry_id uuid references ministries(id);
