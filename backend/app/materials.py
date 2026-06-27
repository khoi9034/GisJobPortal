from __future__ import annotations

import json
import re
from typing import Any

from .ai.prompts import SYSTEM_PROMPT, materials_user_prompt, safe_generation_context
from .ai.service import generate_text


def format_material_context(
    job: dict[str, Any],
    profile: dict[str, Any],
    resume_text: str = "",
    transcript_summary: str = "",
) -> str:
    return (
        f"Candidate: {profile['name']} | {profile['email']} | {profile['location']}\n"
        f"Portfolio: {profile['portfolio']}\n"
        f"Job: {job['title']} at {job['company']} in {job['location']}\n"
        f"Resume summary available: {'yes' if resume_text else 'no'}\n"
        f"Transcript summary used: {'yes' if transcript_summary else 'no'}\n"
        "Rules: include the portfolio, do not include a phone number or GitHub, "
        "do not overclaim, and do not use unsupported seniority labels."
    )


def template_materials(
    job: dict[str, Any],
    profile: dict[str, Any],
    resume_text: str = "",
    transcript_summary: str = "",
) -> dict[str, Any]:
    title = job["title"]
    company = job["company"]
    portfolio = profile["portfolio"]
    fit_summary = job.get("fit_summary") or "This role connects with Khoi's GIS, planning data, and ArcGIS workflow experience."
    resume_angle = job.get("recommended_resume_angle") or "Lead with county GIS, public GIS data, and ArcGIS Enterprise work."

    cover_letter = f"""Dear {company} Hiring Team,

I am excited to apply for the {title} role. I am completing a B.A. in Geography with a GIS minor at UNC-Chapel Hill and currently work as a GIS Analyst Intern with Cabarrus County, where I support ArcGIS Enterprise/Portal, ArcGIS Online, feature services, metadata, public GIS data, parcels, zoning, addresses, and planning-related datasets.

The role stands out because {fit_summary.lower()} I would bring hands-on county GIS experience, careful public data stewardship, and practical Python/SQL automation skills. I am also building Cabarrus FutureScape, a parcel-based planning intelligence project focused on growth, constraints, and future development analysis.

Portfolio: {portfolio}

Best,
{profile['name']}"""

    followup_email = f"""Subject: Application Follow-Up - {title}

Hi {company} Team,

I recently applied for the {title} role and wanted to briefly share why I'm interested. I'm currently a GIS Analyst Intern with Cabarrus County, where I work with ArcGIS Enterprise/Portal, public GIS data, feature services, metadata, parcels, zoning, and planning-related datasets. I'm also building Cabarrus FutureScape, a parcel-based planning intelligence project focused on growth, constraints, and future development analysis.

I'd be grateful for any consideration and would be happy to share more about my work.

Portfolio: {portfolio}

Best,
{profile['name']}"""

    recruiter_message = (
        f"Hi {company} team, I applied for the {title} role and wanted to share my portfolio: {portfolio}. "
        "My background combines county GIS, ArcGIS Enterprise/Portal, public GIS datasets, parcels, zoning, "
        "planning data, and Python/SQL automation. I would be glad to share more if helpful."
    )

    resume_bullets = [
        "Supported Cabarrus County GIS workflows across ArcGIS Enterprise/Portal, ArcGIS Online, feature services, web maps, and metadata.",
        "Organized public GIS data and GIS Hub/Open Data workflows for parcels, zoning, addresses, boundaries, and planning-related layers.",
        "Built Cabarrus FutureScape, a parcel-based planning intelligence project for growth, constraints, and future development analysis.",
        resume_angle,
    ]

    return {
        "fit_summary": fit_summary,
        "cover_letter": cover_letter,
        "followup_email": followup_email,
        "recruiter_message": recruiter_message,
        "resume_angle": resume_angle,
        "resume_bullets": resume_bullets,
        "missing_skills_explanation": "Review the posting for any missing preferred tools or credentials before applying.",
        "required_documents_checklist": "",
        "application_notes": "Review every material before submitting. This app does not auto-submit applications.",
        "context": format_material_context(job, profile, resume_text, transcript_summary),
        "generation_mode": "template_fallback",
    }


def parse_ai_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_ai_materials(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = {**fallback, **{key: value for key, value in payload.items() if value}}
    bullets = result.get("resume_bullets")
    if isinstance(bullets, str):
        result["resume_bullets"] = [line.strip("- ").strip() for line in bullets.splitlines() if line.strip()]
    if not isinstance(result.get("resume_bullets"), list):
        result["resume_bullets"] = fallback["resume_bullets"]
    result["generation_mode"] = "pony_alpha"
    return result


def generate_materials(
    job: dict[str, Any],
    profile: dict[str, Any],
    resume_text: str = "",
    transcript_summary: str = "",
    checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = template_materials(job, profile, resume_text, transcript_summary)
    context = safe_generation_context(job, profile, resume_text, transcript_summary, checklist)
    response, mode = generate_text(SYSTEM_PROMPT, materials_user_prompt(context), temperature=0.4)
    if mode != "pony_alpha":
        return fallback
    try:
        return normalize_ai_materials(parse_ai_json(response), fallback)
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback
