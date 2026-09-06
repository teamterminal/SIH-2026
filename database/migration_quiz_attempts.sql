-- ============================================================
-- Store each generated quiz attempt and its questions/answers,
-- so a user can look back at past quizzes, not just a score trend.
-- ============================================================

create table quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid references profiles(id) on delete cascade,
  ministry_id uuid references ministries(id),
  job_role_id uuid references job_roles(id),
  source text default 'initial',   -- 'initial', 'reassess', or 'material'
  taken_at timestamptz default now()
);

create table quiz_attempt_questions (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid references quiz_attempts(id) on delete cascade,
  skill_id uuid references skills(id),
  question_text text not null,
  options jsonb not null,
  correct_option text not null,
  selected_option text,             -- filled in once the user answers
  is_correct boolean
);

-- Link each skill score back to the attempt that produced it, so
-- "your progress" can drill from a score down to the actual quiz.
alter table skill_snapshots add column if not exists attempt_id uuid references quiz_attempts(id);

-- RLS: users can only see/write their own attempts and answers.
alter table quiz_attempts enable row level security;

create policy "Users can insert their own quiz attempts"
  on quiz_attempts for insert
  with check (profile_id = auth.uid());

create policy "Users can view their own quiz attempts"
  on quiz_attempts for select
  using (profile_id = auth.uid());

alter table quiz_attempt_questions enable row level security;

create policy "Users can insert their own quiz attempt questions"
  on quiz_attempt_questions for insert
  with check (attempt_id in (select id from quiz_attempts where profile_id = auth.uid()));

create policy "Users can view their own quiz attempt questions"
  on quiz_attempt_questions for select
  using (attempt_id in (select id from quiz_attempts where profile_id = auth.uid()));
