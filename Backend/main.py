"""
Sankhya Setu — quiz generation backend.

Endpoints, called from the website:

  POST /generate-quiz   -> called when the user clicks "take a quiz"
                            for the standard role-based assessment.
                            Asks an open-source LLM (via LangChain +
                            Hugging Face) for a 20-question MCQ quiz,
                            stores it, and returns it WITHOUT the
                            correct answers (those stay server-side).

  POST /submit-quiz     -> called when the user finishes ANY quiz —
                            standard or material-based (see
                            Rag_quiz_generation.py). Scores answers
                            against the stored correct options, writes
                            skill_snapshots, and returns results. This
                            endpoint doesn't need to know or care how
                            the questions were generated.

  (see Rag_quiz_generation.py for POST /generate-quiz-from-material,
  registered below as a router)

Run locally with:
    uvicorn main:app --reload --port 8000

Environment variables needed (see .env.example):
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   (service role key — NOT the anon key)
    HF_TOKEN               (Hugging Face access token)
    HF_MODEL_REPO_ID        (default provided in shared.py)
"""

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shared import (
    supabase, call_llm_for_json, fetch_profile_context, fetch_role_skills,
    HF_MODEL_REPO_ID,
)
from Rag_quiz_generation import router as rag_router

QUESTIONS_PER_QUIZ = 20

app = FastAPI(title="Sankhya Setu Quiz Backend")

# During development, allow any origin. Before a real deployment,
# replace "*" with your actual site's domain(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rag_router)


# ============================================================
# Request / response schemas
# ============================================================
class GenerateQuizRequest(BaseModel):
    profile_id: str


class QuestionOut(BaseModel):
    id: str
    skill: str
    question: str
    options: list[str]


class GenerateQuizResponse(BaseModel):
    attempt_id: str
    questions: list[QuestionOut]


class AnswerIn(BaseModel):
    question_id: str
    selected_option: str


class SubmitQuizRequest(BaseModel):
    attempt_id: str
    answers: list[AnswerIn]


class SkillResult(BaseModel):
    skill: str
    score_percent: float
    required_level: Optional[float] = None


class SubmitQuizResponse(BaseModel):
    attempt_id: str
    overall_score_percent: float
    skills: list[SkillResult]
    current_skill_vector: dict[str, float]


class QuizQuestionLLMOutput(BaseModel):
    skill: str
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option: str


class QuizLLMOutput(BaseModel):
    questions: list[QuizQuestionLLMOutput]


# ============================================================
# Prompt builder (standard role-based quiz only — see
# Rag_quiz_generation.py for the material-based prompt)
# ============================================================
def build_quiz_prompt(profile: dict, skills: list[dict]) -> tuple[str, str]:
    skill_names = [s["name"] for s in skills]
    per_skill = max(1, QUESTIONS_PER_QUIZ // len(skill_names))
    system = (
        "You are an expert quiz writer for India's Official Statistics "
        "System training programs. You output ONLY valid JSON, nothing else."
    )
    user = f"""
Write exactly {QUESTIONS_PER_QUIZ} multiple-choice questions to assess a
government official's CURRENT proficiency in these skills: {", ".join(skill_names)}.

Context on who is taking this quiz:
Job role: {profile["job_roles"]["name"]}
Ministry / Department: {profile["ministries"]["name"] if profile.get("ministries") else "Not specified"}

Spread the questions across the listed skills as evenly as possible
(roughly {per_skill} questions per skill). Each question must have
exactly 4 answer options, with exactly one correct option. Vary
difficulty — include some foundational and some more advanced
questions per skill, since this quiz is meant to measure current
skill level, not just pass/fail.

Respond with ONLY a JSON object in exactly this shape:
{{
  "questions": [
    {{
      "skill": "Exact skill name from the list above",
      "question": "The question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_option": "The exact text of the correct option, matching one of the options above"
    }}
  ]
}}
""".strip()
    return system, user


# ============================================================
# Endpoints
# ============================================================
@app.post("/generate-quiz", response_model=GenerateQuizResponse)
def generate_quiz(req: GenerateQuizRequest):
    profile = fetch_profile_context(req.profile_id)
    skills = fetch_role_skills(profile["job_roles"]["id"])
    skill_name_to_id = {s["name"]: s["id"] for s in skills}

    q_system, q_user = build_quiz_prompt(profile, skills)
    quiz: QuizLLMOutput = call_llm_for_json(q_system, q_user, QuizLLMOutput)

    valid_questions = [
        q for q in quiz.questions
        if q.skill in skill_name_to_id and q.correct_option in q.options
    ]
    if not valid_questions:
        raise HTTPException(status_code=502, detail="The model didn't return any usable questions")

    attempt = (
        supabase.table("quiz_attempts")
        .insert({
            "profile_id": req.profile_id,
            "ministry_id": profile.get("ministry_id"),
            "job_role_id": profile["job_roles"]["id"],
            "source": "initial",
        })
        .execute()
    )
    attempt_id = attempt.data[0]["id"]

    question_rows = [
        {
            "attempt_id": attempt_id,
            "skill_id": skill_name_to_id[q.skill],
            "question_text": q.question,
            "options": q.options,
            "correct_option": q.correct_option,
        }
        for q in valid_questions
    ]
    inserted = supabase.table("quiz_attempt_questions").insert(question_rows).execute()

    questions_out = [
        QuestionOut(
            id=row["id"],
            skill=next(q.skill for q in valid_questions if q.question == row["question_text"]),
            question=row["question_text"],
            options=row["options"],
        )
        for row in inserted.data
    ]

    return GenerateQuizResponse(attempt_id=attempt_id, questions=questions_out)


@app.post("/submit-quiz", response_model=SubmitQuizResponse)
def submit_quiz(req: SubmitQuizRequest):
    attempt = (
        supabase.table("quiz_attempts")
        .select("*")
        .eq("id", req.attempt_id)
        .single()
        .execute()
    )
    if not attempt.data:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")

    questions = (
        supabase.table("quiz_attempt_questions")
        .select("*, skills(id, name)")
        .eq("attempt_id", req.attempt_id)
        .execute()
    ).data

    answers_by_question = {a.question_id: a.selected_option for a in req.answers}

    per_skill_correct: dict[str, int] = {}
    per_skill_total: dict[str, int] = {}
    skill_id_to_name = {}

    for q in questions:
        selected = answers_by_question.get(q["id"])
        is_correct = selected is not None and selected == q["correct_option"]
        supabase.table("quiz_attempt_questions").update({
            "selected_option": selected,
            "is_correct": is_correct,
        }).eq("id", q["id"]).execute()

        skill_id = q["skill_id"]
        skill_name = q["skills"]["name"] if q.get("skills") else "Unknown"
        skill_id_to_name[skill_id] = skill_name
        per_skill_total[skill_id] = per_skill_total.get(skill_id, 0) + 1
        if is_correct:
            per_skill_correct[skill_id] = per_skill_correct.get(skill_id, 0) + 1

    role_skills = (
        supabase.table("job_role_skills")
        .select("skill_id, required_level")
        .eq("job_role_id", attempt.data["job_role_id"])
        .execute()
    ).data or []
    required_by_skill_id = {r["skill_id"]: r["required_level"] for r in role_skills}

    results = []
    snapshot_rows = []
    current_skill_vector = {}
    for skill_id, total in per_skill_total.items():
        correct = per_skill_correct.get(skill_id, 0)
        score_percent = round((correct / total) * 100, 1)
        skill_name = skill_id_to_name[skill_id]
        score_0_to_10_precise = round(score_percent / 10, 1)
        score_0_to_10_int = round(score_percent / 10)
        current_skill_vector[skill_name] = score_0_to_10_precise

        results.append(SkillResult(
            skill=skill_name,
            score_percent=score_percent,
            required_level=required_by_skill_id.get(skill_id),
        ))
        snapshot_rows.append({
            "profile_id": attempt.data["profile_id"],
            "attempt_id": req.attempt_id,
            "skill_id": skill_id,
            "score": score_0_to_10_int,
            "source": attempt.data.get("source", "initial"),
        })

    if snapshot_rows:
        supabase.table("skill_snapshots").insert(snapshot_rows).execute()

    overall = round(sum(r.score_percent for r in results) / len(results), 1) if results else 0.0

    return SubmitQuizResponse(
        attempt_id=req.attempt_id,
        overall_score_percent=overall,
        skills=results,
        current_skill_vector=current_skill_vector,
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": HF_MODEL_REPO_ID}
