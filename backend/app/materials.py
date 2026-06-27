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


def job_focus(job: dict[str, Any]) -> str:
    text = " ".join(str(job.get(key, "")) for key in ["title", "description", "requirements", "fit_summary"]).lower()
    focus = []
    if "arcgis" in text or "portal" in text:
        focus.append("ArcGIS Enterprise/Portal, ArcGIS Online, and web GIS")
    if "python" in text or "sql" in text or "automation" in text or "scripting" in text:
        focus.append("Python/SQL automation")
    if "spatial" in text or "geospatial" in text:
        focus.append("spatial analysis and geospatial data stewardship")
    if any(word in text for word in ["parcel", "zoning", "planning", "land use"]):
        focus.append("parcels, zoning, and planning data")
    focus = focus[:3]
    if len(focus) > 1:
        return f"{', '.join(focus[:-1])}, and {focus[-1]}"
    return focus[0] if focus else "GIS data workflows"


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
    focus = job_focus(job)

    cover_letter = f"""Dear {company} Hiring Team,

I am applying for the {title} role because it connects directly with {focus}. I am completing a B.A. in Geography with a GIS minor at UNC-Chapel Hill and currently work as a GIS Analyst Intern with Cabarrus County, where I support ArcGIS Enterprise/Portal, ArcGIS Online, ArcGIS Hub, feature services, metadata, public GIS data, parcels, zoning, addresses, and planning-related datasets.

At Cabarrus County, my work has centered on careful public GIS data stewardship, publishing and organizing GIS layers, and making planning-related data easier to use. That background fits this posting's emphasis on {focus}, and I would bring a practical local-government GIS perspective with a clear readiness to keep learning. I am also building Cabarrus FutureScape, a parcel-based planning intelligence project focused on growth, constraints, and future development analysis.

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
        "My background combines Cabarrus County GIS, ArcGIS Enterprise/Portal, ArcGIS Online/Hub, public GIS datasets, parcels, zoning, "
        "planning data, and Python/SQL automation. I would be glad to share more if helpful."
    )

    resume_bullets = [
        "Supported Cabarrus County GIS workflows across ArcGIS Enterprise/Portal, ArcGIS Online, feature services, web maps, and metadata.",
        "Organized public GIS data and GIS Hub/Open Data workflows for parcels, zoning, addresses, boundaries, and planning-related layers.",
        "Built Cabarrus FutureScape, a parcel-based planning intelligence project for growth, constraints, and future development analysis.",
        f"Position resume summary around {focus} while keeping claims tied to current Cabarrus County intern work.",
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
