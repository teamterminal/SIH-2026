-- ============================================================
-- A skill_snapshots row is written every time someone takes a quiz,
-- so one officer can have many rows for the same skill over time
-- (their score history). For admin aggregates we only want each
-- officer's CURRENT standing per skill — their most recent row —
-- not every historical attempt averaged together.
--
-- "distinct on (profile_id, skill_id) ... order by ... taken_at desc"
-- keeps exactly one row per officer+skill: the newest one.
--
-- No grants are added here on purpose — this view is only meant to
-- be queried by the backend's service-role key (Backend/admin.py),
-- not directly by logged-in users in the browser.
-- ============================================================

create or replace view latest_skill_snapshots as
select distinct on (profile_id, skill_id)
  profile_id,
  skill_id,
  score,
  taken_at
from skill_snapshots
order by profile_id, skill_id, taken_at desc;
