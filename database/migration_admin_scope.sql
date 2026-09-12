-- ============================================================
-- Add admin_scope to profiles: the switch that says whether this
-- user is a regular officer or someone who can see summary stats
-- across other users.
--
-- 'none'    -> regular officer, sees only their own data (default,
--              so every existing user is unaffected by this change)
-- 'ministry'-> can see aggregate stats for officers in their OWN
--              ministry_id only
-- 'global'  -> can see aggregate stats across every ministry
--              (e.g. a central/HQ-level admin)
-- ============================================================

alter table profiles
  add column if not exists admin_scope text not null default 'none'
  check (admin_scope in ('none', 'ministry', 'global'));

-- IMPORTANT: your existing "Users can update their own profile" policy
-- lets a logged-in user update ANY column on their own row (that's how
-- profile editing works). RLS controls which ROW you can touch, not
-- which COLUMN — so without the line below, any officer could open
-- their browser console and set their own admin_scope to 'global'.
--
-- This revokes UPDATE permission on just this one column from the
-- "authenticated" role (what logged-in users use via the app), while
-- your backend's service-role key is unaffected and can still change
-- it freely. Users can still SEE their own admin_scope, just not edit it.
revoke update (admin_scope) on profiles from authenticated;

-- To make yourself an admin for testing, run this AFTER the above,
-- replacing the email with your own login email. This runs as YOU in
-- the SQL Editor, which uses the service role, so the revoke above
-- does not block it:
--
-- update profiles
-- set admin_scope = 'global'
-- where id = (select id from auth.users where email = 'you@example.com');
