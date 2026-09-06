-- One row per COMPLETED quiz attempt (every question answered), with
-- its score. This is what "19 quizzes taken," the recent-attempts bar
-- chart, streaks, and test history all read from — none of that
-- existed as a single queryable number before this.

create or replace view quiz_attempt_scores
with (security_invoker = true)
as
select
  qa.id as attempt_id,
  qa.profile_id,
  qa.job_role_id,
  qa.source,
  qa.taken_at,
  count(qaq.id) as question_count,
  count(qaq.id) filter (where qaq.is_correct) as correct_count,
  round(100.0 * count(qaq.id) filter (where qaq.is_correct) / count(qaq.id), 1) as score_percent
from quiz_attempts qa
join quiz_attempt_questions qaq on qaq.attempt_id = qa.id
group by qa.id, qa.profile_id, qa.job_role_id, qa.source, qa.taken_at
-- Only attempts where every question has an answer — an in-progress
-- or abandoned quiz shouldn't count as a real, scored attempt.
having count(qaq.id) filter (where qaq.selected_option is null) = 0;

grant select on quiz_attempt_scores to authenticated;
