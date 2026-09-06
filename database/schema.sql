-- ============================================================
-- SANKHYA SETU — full schema, ordered so every FK target exists
-- before the table that references it is created.
-- ============================================================

-- ---------- 1. skills: the shared catalog, referenced by everything else ----------
create table skills (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  category text
);

-- ---------- 2. job_roles: referenced by profiles, job_role_skills, quiz_questions ----------
create table job_roles (
  id uuid primary key default gen_random_uuid(),
  name text not null unique
);

-- ---------- 3. profiles: extends auth.users (Supabase's built-in table) ----------
-- FK: profiles.id -> auth.users.id (one-to-one; this IS the user, just with extra fields)
-- FK: profiles.job_role_id -> job_roles.id (which role this person holds)
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  job_role_id uuid references job_roles(id),
  full_name text,
  ministry_department text,
  designation text,
  years_in_role int,
  qualification text,
  field_of_study text,
  igot_courses_done text[],
  created_at timestamptz default now()
);

-- ---------- 4. job_role_skills: junction between job_roles and skills ----------
-- FK: job_role_id -> job_roles.id
-- FK: skill_id -> skills.id
-- Composite primary key means one row per (role, skill) pair — no duplicates.
create table job_role_skills (
  job_role_id uuid references job_roles(id) on delete cascade,
  skill_id uuid references skills(id) on delete cascade,
  required_level int not null check (required_level between 0 and 10),
  primary key (job_role_id, skill_id)
);

-- ---------- 5. quiz_questions: each question targets one role + one skill ----------
-- FK: job_role_id -> job_roles.id
-- FK: skill_id -> skills.id
create table quiz_questions (
  id uuid primary key default gen_random_uuid(),
  job_role_id uuid references job_roles(id) on delete cascade,
  skill_id uuid references skills(id) on delete cascade,
  question_text text not null,
  options jsonb not null,        -- e.g. ["Option A", "Option B", "Option C", "Option D"]
  correct_option text not null,
  created_at timestamptz default now()
);

-- ---------- 6. skill_snapshots: a user's score on one skill, at one point in time ----------
-- FK: profile_id -> profiles.id (whose score this is)
-- FK: skill_id -> skills.id (which skill was scored)
-- Multiple rows per (profile, skill) over time = your progress history.
create table skill_snapshots (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid references profiles(id) on delete cascade,
  skill_id uuid references skills(id) on delete cascade,
  score int not null check (score between 0 and 10),
  source text default 'quiz',    -- 'quiz' or 'rag_requiz', so you can tell how the score was produced
  taken_at timestamptz default now()
);

-- ---------- 7. courses: the recommendation catalog ----------
create table courses (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  igot_link text,
  created_at timestamptz default now()
);

-- ---------- 8. course_skills: junction between courses and skills ----------
-- FK: course_id -> courses.id
-- FK: skill_id -> skills.id
-- This is what lets you query "which courses cover the skill this user is weak in".
create table course_skills (
  course_id uuid references courses(id) on delete cascade,
  skill_id uuid references skills(id) on delete cascade,
  primary key (course_id, skill_id)
);

-- ============================================================
-- Row Level Security
-- ============================================================

-- Catalog tables (skills, job_roles, job_role_skills, quiz_questions, courses,
-- course_skills) are read-only reference data: every logged-in user should be
-- able to read them, but only you (via the Supabase dashboard / service role)
-- should write to them — there's no insert/update policy for regular users below.
alter table skills enable row level security;
alter table job_roles enable row level security;
alter table job_role_skills enable row level security;
alter table quiz_questions enable row level security;
alter table courses enable row level security;
alter table course_skills enable row level security;

create policy "Authenticated users can read skills" on skills for select using (auth.role() = 'authenticated');
create policy "Authenticated users can read job_roles" on job_roles for select using (auth.role() = 'authenticated');
create policy "Authenticated users can read job_role_skills" on job_role_skills for select using (auth.role() = 'authenticated');
create policy "Authenticated users can read quiz_questions" on quiz_questions for select using (auth.role() = 'authenticated');
create policy "Authenticated users can read courses" on courses for select using (auth.role() = 'authenticated');
create policy "Authenticated users can read course_skills" on course_skills for select using (auth.role() = 'authenticated');

-- profiles: each user can only see/edit their own row
alter table profiles enable row level security;

create policy "Users can insert their own profile"
  on profiles for insert
  with check (auth.uid() = id);

create policy "Users can view their own profile"
  on profiles for select
  using (auth.uid() = id);

create policy "Users can update their own profile"
  on profiles for update
  using (auth.uid() = id);

-- skill_snapshots: each user can only see/insert their own scores
alter table skill_snapshots enable row level security;

create policy "Users can insert their own skill snapshots"
  on skill_snapshots for insert
  with check (
    profile_id in (select id from profiles where id = auth.uid())
  );

create policy "Users can view their own skill snapshots"
  on skill_snapshots for select
  using (
    profile_id in (select id from profiles where id = auth.uid())
  );
