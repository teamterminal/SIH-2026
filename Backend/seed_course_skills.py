"""
Sankhya Setu — course-to-skill tagger.

Replaces manually editing skill names into course_skills SQL by hand.
This script fetches the REAL skill catalog from the database and asks
the AI to match each course to the skill(s) it actually teaches —
using only skills that already exist (it doesn't invent new ones here;
new skills only get created by seed_required_levels.py, so the skill
catalog has one place it grows from, not two).

Usage:
    python seed_course_skills.py              # tag every untagged course
    python seed_course_skills.py <course_id>  # just one course

Safe to re-run — courses that already have at least one course_skills
row are skipped in batch mode.
"""

import os
import re
import sys
import json
import time
import logging

from dotenv import load_dotenv
from supabase import create_client
from pydantic import BaseModel, ValidationError

from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed-course-skills")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HF_TOKEN = os.environ["HF_TOKEN"]
HF_MODEL_REPO_ID = os.environ.get("HF_MODEL_REPO_ID", "mistralai/Mistral-7B-Instruct-v0.3")
MAX_RETRIES = 3

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_llm = HuggingFaceEndpoint(
    repo_id=HF_MODEL_REPO_ID,
    task="text-generation",
    max_new_tokens=500,
    temperature=0.2,
    huggingfacehub_api_token=HF_TOKEN,
)
chat_model = ChatHuggingFace(llm=_llm)


class CourseSkillMatch(BaseModel):
    matched_skills: list[str] = []


def extract_json_block(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output")
    return match.group(0)


def match_course_to_skills(title: str, description: str, skill_names: list[str]) -> list[str]:
    system = (
        "You match training courses to the skills they teach. You output "
        "ONLY valid JSON, nothing else."
    )
    user = f"""
Course title: {title}
Course description: {description or "(no description provided)"}

Available skills (choose ONLY from this list — do not invent new ones):
{", ".join(skill_names)}

Which of the listed skills does this course teach? A course can match
more than one skill, or none if nothing listed genuinely fits.

Respond with ONLY a JSON object in exactly this shape, using exact
skill names from the list above:
{{"matched_skills": ["Exact Skill Name", "Another Exact Skill Name"]}}
Use an empty list if nothing fits.
""".strip()

    for attempt in range(1, MAX_RETRIES + 1):
        prompt = user
        if attempt > 1:
            prompt += "\n\nRespond with ONLY the JSON object. No markdown, no explanation."
        response = chat_model.invoke([
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ])
        try:
            parsed = json.loads(extract_json_block(response.content))
            validated = CourseSkillMatch(**parsed)
            # Only keep matches that are actually real skill names —
            # don't trust the model to have stuck to the list perfectly.
            valid_lower = {s.strip().lower() for s in skill_names}
            return [s for s in validated.matched_skills if s.strip().lower() in valid_lower]
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            logger.warning("Attempt %d failed for course '%s': %s", attempt, title, e)
            continue

    raise RuntimeError(f"Could not match skills for course '{title}' after {MAX_RETRIES} attempts")


def tag_course(course_id: str, all_skills: list[dict]):
    course = (
        supabase.table("courses")
        .select("id, title, description")
        .eq("id", course_id)
        .single()
        .execute()
    ).data
    if not course:
        logger.error("No course found with id %s", course_id)
        return

    skill_name_to_id = {s["name"].strip().lower(): s["id"] for s in all_skills}
    skill_names = [s["name"] for s in all_skills]

    if not skill_names:
        logger.warning("The skills table is empty — run seed_required_levels.py for at least one role first.")
        return

    logger.info("Matching '%s' against %d skills...", course["title"], len(skill_names))
    matched = match_course_to_skills(course["title"], course.get("description", ""), skill_names)

    if not matched:
        logger.warning("  No matching skills found for '%s' — leaving untagged", course["title"])
        return

    rows = [
        {"course_id": course_id, "skill_id": skill_name_to_id[name.strip().lower()]}
        for name in matched
    ]
    supabase.table("course_skills").upsert(rows, on_conflict="course_id,skill_id").execute()

    for name in matched:
        logger.info("  + %s", name)
    logger.info("Done tagging '%s' (%d skill(s)).", course["title"], len(matched))


def main():
    all_skills = supabase.table("skills").select("id, name").execute().data or []

    if len(sys.argv) >= 2:
        tag_course(sys.argv[1], all_skills)
        return

    # Batch mode: tag every course that doesn't have any course_skills
    # rows yet. Safe to re-run.
    all_course_ids = {c["id"] for c in supabase.table("courses").select("id").execute().data or []}
    tagged_course_ids = {
        r["course_id"]
        for r in supabase.table("course_skills").select("course_id").execute().data or []
    }
    pending = sorted(all_course_ids - tagged_course_ids)

    if not pending:
        logger.info("Every course already has skills tagged. Nothing to do.")
        return

    logger.info("Tagging %d course(s) that don't have skills linked yet...", len(pending))
    failed = []

    for i, course_id in enumerate(pending, start=1):
        logger.info("[%d/%d] course_id=%s", i, len(pending), course_id)
        try:
            tag_course(course_id, all_skills)
        except Exception as e:
            logger.error("Failed to tag course %s: %s", course_id, e)
            failed.append(course_id)
        time.sleep(2)

    logger.info("Batch complete: %d succeeded, %d failed.", len(pending) - len(failed), len(failed))
    if failed:
        logger.info("Failed course_ids (re-run these individually to retry):")
        for course_id in failed:
            logger.info("  python seed_course_skills.py %s", course_id)


if __name__ == "__main__":
    main()
