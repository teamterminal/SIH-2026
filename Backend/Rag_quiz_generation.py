"""
Sankhya Setu — RAG-based quiz generation from uploaded study material.

Called when a user has studied an iGOT course, downloaded its reading
material, and comes back to be re-assessed FROM that specific
material — rather than from general role knowledge, which is what
/generate-quiz in main.py does.

Pipeline, per request:
  1. Extract text from the uploaded PDF.
  2. Split it into chunks and embed them LOCALLY (via a small
     sentence-transformers model, not a Hugging Face API call) — this
     avoids burning extra LLM-provider quota just to build a
     throwaway, per-request vector index.
  3. For each skill the user's role requires, retrieve the most
     relevant chunks and ask the LLM to honestly judge whether the
     material covers that skill well enough to write real questions
     about it. Skills it doesn't cover are skipped — this quiz will
     usually test FEWER than all the role's skills, on purpose.
  4. For each covered skill, generate a small set of questions
     grounded ONLY in the retrieved chunks.
  5. Store the attempt (source='material') and its questions the same
     way main.py's standard quiz does. Scoring, skill_snapshots, and
     results all go through the EXISTING /submit-quiz endpoint in
     main.py, completely unchanged — it only needs an attempt_id and
     doesn't care how the questions were generated.

New dependencies beyond main.py's (see requirements.txt):
    pypdf                    (PDF text extraction)
    langchain-text-splitters (chunking)
    sentence-transformers    (local embedding model — downloads a
                              small model file the first time this
                              runs; needs internet access once)
"""

import io
import logging

from fastapi import APIRouter, UploadFile, Form, File, HTTPException
from pydantic import BaseModel, Field

from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.documents import Document

from shared import supabase, call_llm_for_json, fetch_profile_context, fetch_role_skills, logger

router = APIRouter()

QUESTIONS_PER_COVERED_SKILL = 4
CHUNKS_PER_SKILL = 4
MIN_CHUNK_CHARS = 200  # skip near-empty chunks (blank pages, headers-only, etc.)

# Loaded once at import time and reused across every request — loading
# this fresh per request would be slow. Runs locally on CPU; consumes
# no Hugging Face API quota, unlike the LLM calls below.
_embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


# ============================================================
# Schemas
# ============================================================
class MaterialQuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option: str


class MaterialSkillLLMOutput(BaseModel):
    covered: bool
    questions: list[MaterialQuizQuestion] = []


class QuestionOut(BaseModel):
    id: str
    skill: str
    question: str
    options: list[str]


class GenerateMaterialQuizResponse(BaseModel):
    attempt_id: str
    skills_covered: list[str]
    skills_skipped: list[str]
    questions: list[QuestionOut]


# ============================================================
# PDF -> chunks -> vector store
# ============================================================
def extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages).strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Couldn't extract any text from this PDF — it may be a scanned "
                   "image without a text layer, which this doesn't support yet.",
        )
    return text


def build_vectorstore(text: str) -> InMemoryVectorStore:
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = [c for c in splitter.split_text(text) if len(c.strip()) >= MIN_CHUNK_CHARS]
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="This document doesn't have enough readable text to build a quiz from.",
        )
    docs = [Document(page_content=c) for c in chunks]
    # In-memory and per-request by design — this index only needs to
    # exist for the lifetime of this one upload, not persisted.
    return InMemoryVectorStore.from_documents(docs, _embeddings)


# ============================================================
# Prompt — coverage judgment AND question generation in one call,
# per skill (kept separate from main.py's role-based prompt, since
# this one must ground everything in the retrieved excerpts, not the
# model's general knowledge).
# ============================================================
def build_skill_prompt(skill_name: str, role_name: str, context_chunks: list[str]) -> tuple[str, str]:
    context_text = "\n\n---\n\n".join(context_chunks)
    system = (
        "You write assessment questions strictly grounded in provided "
        "source material, for India's Official Statistics System "
        "training programs. You output ONLY valid JSON, nothing else."
    )
    user = f"""
A government official in the role "{role_name}" has studied the material excerpts
below and wants to be re-assessed on this specific skill: {skill_name}

Source material excerpts:
\"\"\"
{context_text}
\"\"\"

First, judge honestly: does this material actually cover "{skill_name}"
in enough depth to write {QUESTIONS_PER_COVERED_SKILL} genuine
assessment questions grounded in it? If it only mentions the topic in
passing, or not at all, say it is NOT covered — do not force questions
that would rely on outside knowledge instead of this material.

If it IS covered, write exactly {QUESTIONS_PER_COVERED_SKILL}
multiple-choice questions, each with exactly 4 options and one
correct option, based ONLY on the excerpts above.

Respond with ONLY a JSON object in exactly this shape:
{{"covered": true, "questions": [{{"question": "...", "options": ["...", "...", "...", "..."], "correct_option": "..."}}]}}

or, if not covered:
{{"covered": false, "questions": []}}
""".strip()
    return system, user


# ============================================================
# Endpoint
# ============================================================
@router.post("/generate-quiz-from-material", response_model=GenerateMaterialQuizResponse)
async def generate_quiz_from_material(
    profile_id: str = Form(...),
    file: UploadFile = File(...),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported right now")

    profile = fetch_profile_context(profile_id)
    skills = fetch_role_skills(profile["job_roles"]["id"])
    skill_name_to_id = {s["name"]: s["id"] for s in skills}

    file_bytes = await file.read()
    text = extract_pdf_text(file_bytes)
    vectorstore = build_vectorstore(text)

    covered_questions: dict[str, list[MaterialQuizQuestion]] = {}
    skipped_skills: list[str] = []

    for skill in skills:
        matches = vectorstore.similarity_search(skill["name"], k=CHUNKS_PER_SKILL)
        if not matches:
            skipped_skills.append(skill["name"])
            continue

        context_chunks = [m.page_content for m in matches]
        system, user = build_skill_prompt(skill["name"], profile["job_roles"]["name"], context_chunks)

        try:
            # Fewer retries than the standard quiz (2, not 3) — this
            # runs once PER SKILL, so a role with many skills already
            # means many LLM calls per upload. A skill genuinely not
            # covered by the material should fail fast, not burn
            # retries chasing a "yes" that was never coming.
            result: MaterialSkillLLMOutput = call_llm_for_json(system, user, MaterialSkillLLMOutput, max_retries=2)
        except HTTPException:
            logger.warning("Skipping skill '%s' after repeated JSON failures", skill["name"])
            skipped_skills.append(skill["name"])
            continue

        if not result.covered or not result.questions:
            skipped_skills.append(skill["name"])
            continue

        covered_questions[skill["name"]] = result.questions

    if not covered_questions:
        raise HTTPException(
            status_code=422,
            detail="This material didn't cover any of your role's required skills "
                   "well enough to build a quiz from.",
        )

    attempt = (
        supabase.table("quiz_attempts")
        .insert({
            "profile_id": profile_id,
            "ministry_id": profile.get("ministry_id"),
            "job_role_id": profile["job_roles"]["id"],
            "source": "material",
        })
        .execute()
    )
    attempt_id = attempt.data[0]["id"]

    question_rows = []
    for skill_name, questions in covered_questions.items():
        for q in questions:
            if q.correct_option not in q.options:
                continue
            question_rows.append({
                "attempt_id": attempt_id,
                "skill_id": skill_name_to_id[skill_name],
                "question_text": q.question,
                "options": q.options,
                "correct_option": q.correct_option,
            })

    if not question_rows:
        raise HTTPException(status_code=502, detail="The model didn't return any usable questions from this material")

    inserted = supabase.table("quiz_attempt_questions").insert(question_rows).execute()

    questions_out = [
        QuestionOut(
            id=row["id"],
            skill=next(
                s for s, qs in covered_questions.items()
                for q in qs if q.question == row["question_text"]
            ),
            question=row["question_text"],
            options=row["options"],
        )
        for row in inserted.data
    ]

    return GenerateMaterialQuizResponse(
        attempt_id=attempt_id,
        skills_covered=list(covered_questions.keys()),
        skills_skipped=skipped_skills,
        questions=questions_out,
    )
