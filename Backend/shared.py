"""
Sankhya Setu — shared backend setup.

Both main.py and Rag_quiz_generation.py import from here. Neither
imports the other directly — main.py registers Rag_quiz_generation's
router, so the reverse import would create a circular dependency.
"""

"""
Sankhya Setu — shared backend setup.
"""

import os
import re
import json
import logging
import urllib.request
import urllib.error

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quiz-backend")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HF_TOKEN = os.environ["HF_TOKEN"]

HF_MODEL_REPO_ID = os.environ.get(
    "HF_MODEL_REPO_ID",
    "google/gemma-3-27b-it"
)

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

MAX_LLM_RETRIES = 3

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _extract_json_block(text: str) -> str:
    """Pull the first JSON object or array from model output."""
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)

    if not match:
        raise ValueError("No JSON object found in model output")

    return match.group(0)


def _call_groq(system_prompt: str, user_prompt: str) -> str:
        """Call Groq's OpenAI-compatible chat completion API."""
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "temperature": 0.4,
            "max_completion_tokens": 3000,
            "response_format": {
                "type": "json_object"
            },
        }
    
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "SankhyaSetu/1.0",
            },
            method="POST",
        )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        return result["choices"][0]["message"]["content"]

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")

        logger.error(
            "Groq API error %s: %s",
            e.code,
            error_body,
        )

        raise HTTPException(
            status_code=502,
            detail=f"Groq API error {e.code}: {error_body}",
        )

    except Exception as e:
        logger.exception("Groq request failed")

        raise HTTPException(
            status_code=502,
            detail=f"Groq request failed: {str(e)}",
        )


def call_llm_for_json(
    system_prompt: str,
    user_prompt: str,
    validate_with,
    max_retries: int = MAX_LLM_RETRIES,
) -> BaseModel:
    """
    Call Groq and validate the returned JSON against the
    supplied Pydantic model.
    """

    last_error = None

    for attempt in range(1, max_retries + 1):

        prompt = user_prompt

        if attempt > 1:
            prompt += (
                "\n\nYour previous response could not be parsed as valid JSON. "
                "Respond with ONLY the JSON object. "
                "No markdown code fences, no explanation, "
                "no text before or after the JSON."
            )

        raw_text = _call_groq(
            system_prompt,
            prompt,
        )

        try:
            json_block = _extract_json_block(raw_text)
            parsed = json.loads(json_block)

            return validate_with(**parsed)

        except (
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ) as e:

            last_error = e

            logger.warning(
                "LLM JSON parse/validation failed on attempt %d: %s",
                attempt,
                e,
            )

            continue

    raise HTTPException(
        status_code=502,
        detail=(
            f"The model failed to return a usable response "
            f"after {max_retries} attempts: {last_error}"
        ),
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
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    if not profile.get("job_roles"):
        raise HTTPException(
            status_code=400,
            detail="This profile has no job role selected yet",
        )

    return profile


def fetch_role_skills(job_role_id: str) -> list[dict]:
    """Fetch skills relevant to this job role."""

    result = (
        supabase.table("job_role_skills")
        .select("skill_id, required_level, skills(id, name)")
        .eq("job_role_id", job_role_id)
        .execute()
    )

    rows = result.data or []

    skills = [
        {
            "id": r["skills"]["id"],
            "name": r["skills"]["name"],
            "required_level": r["required_level"],
        }
        for r in rows
        if r.get("skills")
    ]

    if not skills:
        raise HTTPException(
            status_code=400,
            detail="No skills are configured for this job role yet",
        )

    return skills
