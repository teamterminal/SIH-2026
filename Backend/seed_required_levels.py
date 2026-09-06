"""
Sankhya Setu — required skill vector seeder.

Run this ONCE per job role (not per user, not per quiz attempt). There
is no fixed, pre-curated list of skills per role — this script asks
the AI to decide BOTH which skills apply to a role AND the required
level for each, then writes the result into job_role_skills.

To keep skill vectors comparable across roles, the AI is shown the
EXISTING skills catalog first and asked to reuse matching skills
rather than invent near-duplicates (e.g. "Data Visualization" vs
"Data Viz Skills" for two different roles, which would silently break
any comparison between them). It only proposes a brand new skill when
nothing in the existing catalog fits. The catalog starts empty (or
however populated it already is) and grows naturally as each role
gets seeded — nobody has to hand-curate it in advance.

Usage:
    python seed_required_levels.py <job_role_id>

Re-running this for a role overwrites its existing required_level
values and can add new skills, so use it deliberately, not as part of
any live request path.
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
logger = logging.getLogger("seed-required-levels")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HF_TOKEN = os.environ["HF_TOKEN"]
HF_MODEL_REPO_ID = os.environ.get("HF_MODEL_REPO_ID", "mistralai/Mistral-7B-Instruct-v0.3")
MAX_RETRIES = 3

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_llm = HuggingFaceEndpoint(
    repo_id=HF_MODEL_REPO_ID,
    task="text-generation",
    max_new_tokens=1500,
    temperature=0.3,
    huggingfacehub_api_token=HF_TOKEN,
)
chat_model = ChatHuggingFace(llm=_llm)


class NewSkill(BaseModel):
    name: str
    category: str = ""
    required_level: int


class SkillPlanOutput(BaseModel):
    existing_skills: dict[str, int] = {}
    new_skills: list[NewSkill] = []


def extract_json_block(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output")
    return match.group(0)


def generate_skill_plan(role_name: str, ministry_name: str, existing_skill_names: list[str]) -> SkillPlanOutput:
    system = (
        "You are an expert in competency frameworks for India's Official "
        "Statistics System. You output ONLY valid JSON, nothing else."
    )
    catalog_text = ", ".join(existing_skill_names) if existing_skill_names else "(catalog is empty so far)"
    user = f"""
Job role: {role_name}
Ministry / Department: {ministry_name or "Not specified"}

Existing skill catalog (skills already used for other roles):
{catalog_text}

Decide which skills someone in this role genuinely needs, and how
proficient (0-10) they need to be at each.

IMPORTANT: Prefer reusing a skill from the existing catalog above over
inventing a new one, even if the wording isn't a perfect match — skill
vectors are compared across roles, so fragmenting similar skills under
different names breaks that comparison. Only propose a new skill if
nothing in the existing catalog is a reasonable fit.

Respond with ONLY a JSON object in exactly this shape:
{{
  "existing_skills": {{"Exact catalog skill name": 7}},
  "new_skills": [
    {{"name": "New skill name", "category": "short category label", "required_level": 6}}
  ]
}}
Omit "new_skills" (use an empty list) if the existing catalog fully covers this role.
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
            return SkillPlanOutput(**parsed)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            logger.warning("Attempt %d failed for role '%s': %s", attempt, role_name, e)
            continue

    raise RuntimeError(f"Could not generate a skill plan for role '{role_name}' after {MAX_RETRIES} attempts")


def get_or_create_skill(name: str, category: str, existing_by_lower_name: dict[str, dict]) -> str:
    """Look up a skill case-insensitively before creating one, so the
    AI capitalizing/rewording something slightly doesn't create an
    accidental duplicate of a skill that already exists."""
    match = existing_by_lower_name.get(name.strip().lower())
    if match:
        return match["id"]

    inserted = supabase.table("skills").insert({"name": name, "category": category}).execute()
    new_row = inserted.data[0]
    existing_by_lower_name[name.strip().lower()] = new_row
    logger.info("  + created new skill: %s", name)
    return new_row["id"]


def seed_role(job_role_id: str):
    role = (
        supabase.table("job_roles")
        .select("id, name")
        .eq("id", job_role_id)
        .single()
        .execute()
    ).data
    if not role:
        logger.error("No job role found with id %s", job_role_id)
        return

    # Ministry is optional context, not required to seed a role.
    sample_profile = (
        supabase.table("profiles")
        .select("ministries(name)")
        .eq("job_role_id", job_role_id)
        .limit(1)
        .execute()
    ).data
    ministry_name = ""
    if sample_profile and sample_profile[0].get("ministries"):
        ministry_name = sample_profile[0]["ministries"]["name"]

    all_skills = supabase.table("skills").select("id, name, category").execute().data or []
    existing_by_lower_name = {s["name"].strip().lower(): s for s in all_skills}
    existing_names = [s["name"] for s in all_skills]

    logger.info("Generating skill plan for '%s' against a catalog of %d existing skills...", role["name"], len(existing_names))
    plan = generate_skill_plan(role["name"], ministry_name, existing_names)

    role_skill_rows = []

    for skill_name, level in plan.existing_skills.items():
        match = existing_by_lower_name.get(skill_name.strip().lower())
        if not match:
            logger.warning("Model referenced '%s' as existing but it wasn't found in the catalog — skipping", skill_name)
            continue
        role_skill_rows.append({"job_role_id": job_role_id, "skill_id": match["id"], "required_level": level})

    for new_skill in plan.new_skills:
        skill_id = get_or_create_skill(new_skill.name, new_skill.category, existing_by_lower_name)
        role_skill_rows.append({"job_role_id": job_role_id, "skill_id": skill_id, "required_level": new_skill.required_level})

    if not role_skill_rows:
        logger.warning("No skills were generated for role '%s' — nothing to save", role["name"])
        return

    supabase.table("job_role_skills").upsert(
        role_skill_rows, on_conflict="job_role_id,skill_id"
    ).execute()

    for row in role_skill_rows:
        name = (
            next((s["name"] for s in all_skills if s["id"] == row["skill_id"]), None)
            or next((n.name for n in plan.new_skills if n.name.strip().lower() in existing_by_lower_name
                     and existing_by_lower_name[n.name.strip().lower()]["id"] == row["skill_id"]), row["skill_id"])
        )
        logger.info("  %s -> %d", name, row["required_level"])

    logger.info("Done seeding '%s' (%d skills).", role["name"], len(role_skill_rows))


def main():
    if len(sys.argv) >= 2 and sys.argv[1] != "--all":
        seed_role(sys.argv[1])
        return

    # Batch mode: seed every role that doesn't already have any skills
    # linked yet. Safe to re-run — roles that already have job_role_skills
    # rows are skipped, so an interrupted run can just be started again.
    all_role_ids = {r["id"] for r in supabase.table("job_roles").select("id").execute().data or []}
    seeded_role_ids = {
        r["job_role_id"]
        for r in supabase.table("job_role_skills").select("job_role_id").execute().data or []
    }
    pending = sorted(all_role_ids - seeded_role_ids)

    if not pending:
        logger.info("Every role already has skills seeded. Nothing to do.")
        return

    logger.info("Seeding %d role(s) that don't have skills yet...", len(pending))
    failed = []

    for i, role_id in enumerate(pending, start=1):
        logger.info("[%d/%d] role_id=%s", i, len(pending), role_id)
        try:
            seed_role(role_id)
        except Exception as e:
            logger.error("Failed to seed role %s: %s", role_id, e)
            failed.append(role_id)

        # Be gentle on Hugging Face's free-tier rate limits across a
        # large batch. If you hit 429 errors even with this delay,
        # increase it or spread the run across multiple sessions.
        time.sleep(2)

    logger.info("Batch complete: %d succeeded, %d failed.", len(pending) - len(failed), len(failed))
    if failed:
        logger.info("Failed role_ids (re-run these individually to retry):")
        for role_id in failed:
            logger.info("  python seed_required_levels.py %s", role_id)


if __name__ == "__main__":
    main()

