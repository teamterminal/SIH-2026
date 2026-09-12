"""
Sankhya Setu — admin aggregate endpoints.

Provides SUMMARY statistics across officers (average score per skill,
weakest skills first) for training administrators — never raw,
per-officer answers. Access is gated by each profile's admin_scope
column ('none' | 'ministry' | 'global'), which only the backend's
service-role key is allowed to change (see migration_admin_scope.sql).
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from shared import supabase, logger

router = APIRouter(prefix="/admin")


class SkillGap(BaseModel):
    skill: str
    average_score: float   # 0-10 scale, same as skill_snapshots.score
    officer_count: int      # how many distinct officers this average is based on


class SkillGapsResponse(BaseModel):
    scope: str                     # 'ministry' or 'global' — so the frontend can label the page
    ministry_id: Optional[str]     # None when scope is 'global'
    skills: list[SkillGap]         # sorted weakest (lowest average) first


def _get_requester_or_403(authorization: Optional[str]) -> dict:
    """
    Identify the caller from their own Supabase session token instead of
    trusting a profile id supplied by the client — otherwise anyone could
    pass a different (admin) profile's id and read that ministry's data.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()

    try:
        user_response = supabase.auth.get_user(token)
    except Exception:
        logger.warning("Rejected admin request: token validation failed")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user = getattr(user_response, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    result = (
        supabase.table("profiles")
        .select("admin_scope, ministry_id")
        .eq("id", user.id)
        .single()
        .execute()
    )
    profile = result.data
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile["admin_scope"] not in ("ministry", "global"):
        raise HTTPException(status_code=403, detail="This account doesn't have admin access")
    return profile


@router.get("/skill-gaps", response_model=SkillGapsResponse)
def get_skill_gaps(authorization: Optional[str] = Header(None)):
    requester = _get_requester_or_403(authorization)
    scope = requester["admin_scope"]

    # Step 1: which officers' data are we allowed to include?
    profile_ids = None
    if scope == "ministry":
        ministry_rows = (
            supabase.table("profiles")
            .select("id")
            .eq("ministry_id", requester["ministry_id"])
            .execute()
        ).data or []
        profile_ids = [r["id"] for r in ministry_rows]
        if not profile_ids:
            return SkillGapsResponse(scope=scope, ministry_id=requester["ministry_id"], skills=[])

    # Step 2: each officer's MOST RECENT score per skill (not every
    # historical attempt — an officer who improved shouldn't have an
    # old, lower score dragging the ministry average down forever).
    query = supabase.table("latest_skill_snapshots").select("profile_id, skill_id, score")
    if profile_ids is not None:
        query = query.in_("profile_id", profile_ids)
    snapshot_rows = query.execute().data or []

    if not snapshot_rows:
        return SkillGapsResponse(scope=scope, ministry_id=requester.get("ministry_id"), skills=[])

    # Step 3: map skill_id -> name once, then average in plain Python
    # (small dataset for a prototype; no need for a heavier tool here).
    skill_ids = list({row["skill_id"] for row in snapshot_rows})
    skills_lookup = {
        s["id"]: s["name"]
        for s in supabase.table("skills").select("id, name").in_("id", skill_ids).execute().data
    }

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in snapshot_rows:
        name = skills_lookup.get(row["skill_id"], "Unknown skill")
        totals[name] = totals.get(name, 0) + row["score"]
        counts[name] = counts.get(name, 0) + 1

    skills_out = [
        SkillGap(
            skill=name,
            average_score=round(totals[name] / counts[name], 2),
            officer_count=counts[name],
        )
        for name in totals
    ]
    skills_out.sort(key=lambda s: s.average_score)  # weakest first

    return SkillGapsResponse(
        scope=scope,
        ministry_id=requester.get("ministry_id") if scope == "ministry" else None,
        skills=skills_out,
    )
