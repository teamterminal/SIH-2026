"""
Sankhya Setu — shared backend setup.

Both main.py and Rag_quiz_generation.py import from here. Neither
imports the other directly — main.py registers Rag_quiz_generation's
router, so the reverse import would create a circular dependency.
"""

import os
import re
import json
import logging

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from supabase import create_client, Client

from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quiz-backend")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HF_TOKEN = os.environ["HF_TOKEN"]
MAX_LLM_RETRIES = 3

# Supports both HF_MODEL_REPO_ID="org/model" (provider auto-selected)
# and the older HF_MODEL_REPO_ID="org/model:provider" format from
# earlier in this project — huggingface_hub now requires provider as
# its own separate argument, not embedded in the model string, so
# this splits it out rather than requiring another .env edit.
_raw_model = os.environ.get("HF_MODEL_REPO_ID", "google/gemma-3-27b-it")
if ":" in _raw_model:
    HF_MODEL_REPO_ID, HF_PROVIDER = _raw_model.split(":", 1)
else:
    HF_MODEL_REPO_ID = _raw_model
    HF_PROVIDER = os.environ.get("HF_PROVIDER", "auto")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_llm = HuggingFaceEndpoint(
    repo_id=HF_MODEL_REPO_ID,
    provider=HF_PROVIDER,
    task="text-generation",
    max_new_tokens=3000,
    temperature=0.4,
    huggingfacehub_api_token=HF_TOKEN,
)
chat_model = ChatHuggingFace(llm=_llm)


def _extract_json_block(text: str) -> str:
    """Pull the first {...} or [...] block out of the model's raw
    output, in case it added markdown fences or explanation text
    around the JSON despite being told not to."""
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output")
    return match.group(0)


def call_llm_for_json(system_prompt: str, user_prompt: str, validate_with, max_retries: int = MAX_LLM_RETRIES) -> BaseModel:
    """Shared retry/validation loop. Open-source models are noticeably
    less reliable than GPT-4/Claude at strictly returning valid JSON,
    so this assumes failure is common and treats it as a normal case
    to recover from, not an edge case."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        prompt = user_prompt
        if attempt > 1:
            prompt += (
                "\n\nYour previous response could not be parsed as valid JSON. "
                "Respond with ONLY the JSON object. No markdown code fences, "
                "no explanation, no text before or after the JSON."
            )
        response = chat_model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])
        raw_text = response.content
        try:
            json_block = _extract_json_block(raw_text)
            parsed = json.loads(json_block)
            return validate_with(**parsed)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning("LLM JSON parse/validation failed on attempt %d: %s", attempt, e)
            continue
    raise HTTPException(
        status_code=502,
        detail=f"The model failed to return a usable response after {max_retries} attempts: {last_error}",
    )


def fetch_profile_context(profile_id: str) -> dict:
    """Pull the job-related details that personalize quiz generation."""
    result = (
        supabase.table("profiles")
        .select("*, ministries(id, name), job_roles(id, name)")
        .eq("id", profile_id)
        .single()
        .execute()
    )
    profile = result.data
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not profile.get("job_roles"):
        raise HTTPException(status_code=400, detail="This profile has no job role selected yet")
    return profile


def fetch_role_skills(job_role_id: str) -> list[dict]:
    """The set of skills relevant to this role, along with the
    required_level cached in job_role_skills — generated once per role
    by seed_required_levels.py, not per quiz attempt."""
    result = (
        supabase.table("job_role_skills")
        .select("skill_id, required_level, skills(id, name)")
        .eq("job_role_id", job_role_id)
        .execute()
    )
    rows = result.data or []
    skills = [
        {"id": r["skills"]["id"], "name": r["skills"]["name"], "required_level": r["required_level"]}
        for r in rows if r.get("skills")
    ]
    if not skills:
        raise HTTPException(status_code=400, detail="No skills are configured for this job role yet")
    return skills
