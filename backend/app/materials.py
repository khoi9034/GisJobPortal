from __future__ import annotations

from typing import Any


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
        f"Resume source: {'private/resume/resume_extracted.md' if resume_text else 'config/profile.yaml'}\n"
        f"Transcript source: {'private/transcript/transcript_summary.md' if transcript_summary else 'not used'}\n"
        "Rules: include the portfolio, do not include a phone number or GitHub, "
        "do not overclaim, and do not use unsupported seniority labels."
    )


def generate_materials(
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
        "resume_bullets": resume_bullets,
        "context": format_material_context(job, profile, resume_text, transcript_summary),
    }
