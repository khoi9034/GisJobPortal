from __future__ import annotations

import json
import re
from typing import Any

PORTFOLIO = "https://portfolio-gamma-six-p15gdz1e0v.vercel.app/"

SYSTEM_PROMPT = """You write concise GIS job application materials for Khoi Nguyen.

Rules:
- Do not invent experience, credentials, coursework, tools, awards, employers, or seniority.
- Do not say Khoi is an expert.
- Do not include a phone number.
- Do not include GitHub unless the provided profile context includes it.
- Always include this portfolio link where appropriate: https://portfolio-gamma-six-p15gdz1e0v.vercel.app/
- Emphasize Cabarrus County GIS Analyst Intern experience when relevant.
- Emphasize ArcGIS Enterprise, Portal, ArcGIS Online, ArcGIS Hub, metadata, public GIS workflows, parcels, zoning, planning data, Python/ArcPy, SQL/PostGIS, and Cabarrus FutureScape when relevant.
- Keep writing concise, direct, truthful, and tailored.
- Return only valid JSON when JSON is requested.
"""

SENSITIVE_PATTERNS = [
    r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b",
    r"[A-Za-z]:\\[^\n\r\t]+",
    r"\bprivate[/\\][^\s]+",
    r"\bgenerated[/\\]application_packets[/\\][^\s]+",
    r"\.env[^\s]*",
    r"OPENROUTER_API_KEY\s*=\s*[^\s]+",
    r"VERCEL_TOKEN\s*=\s*[^\s]+",
    r"vcp_[A-Za-z0-9]+",
]


def sanitize_text(value: Any, limit: int = 2400) -> str:
    text = str(value or "")
    for pattern in SENSITIVE_PATTERNS:
        text = re.sub(pattern, "[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {sanitize_text(key, 120): sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def safe_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": sanitize_text(profile.get("name"), 120),
        "location": sanitize_text(profile.get("location"), 120),
        "portfolio": profile.get("portfolio") or PORTFOLIO,
        "education": sanitize_value(profile.get("education", [])),
        "experience": sanitize_value(profile.get("experience", [])),
        "skills": sanitize_value(profile.get("skills", [])),
        "projects": sanitize_value(profile.get("projects", [])),
        "target_roles": sanitize_value(profile.get("target_roles", [])),
        "writing_style_rules": sanitize_value(profile.get("writing_style_rules", [])),
    }


def safe_generation_context(
    job: dict[str, Any],
    profile: dict[str, Any],
    resume_summary: str = "",
    transcript_summary: str = "",
    checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "profile": safe_profile(profile),
        "resume_summary": sanitize_text(resume_summary),
        "transcript_summary": sanitize_text(transcript_summary) if transcript_summary else "",
        "job": {
            "title": sanitize_text(job.get("title"), 160),
            "company": sanitize_text(job.get("company"), 160),
            "location": sanitize_text(job.get("location"), 160),
            "description": sanitize_text(job.get("description"), 4000),
            "requirements": sanitize_text(job.get("requirements"), 2200),
        },
        "scoring_breakdown": job.get("scoring_breakdown") or {},
        "missing_skills": job.get("missing_skills") or [],
        "fit_reasons": job.get("fit_reasons") or [],
        "portfolio": profile.get("portfolio") or PORTFOLIO,
        "document_checklist": checklist or job.get("document_checklist") or {},
    }


def materials_user_prompt(context: dict[str, Any]) -> str:
    schema = {
        "fit_summary": "2 concise sentences explaining fit",
        "cover_letter": "concise tailored cover letter",
        "followup_email": "short direct follow-up email with subject line",
        "recruiter_message": "short recruiter or director message",
        "resume_angle": "one concise resume positioning angle",
        "resume_bullets": ["3-5 truthful resume bullet suggestions"],
        "missing_skills_explanation": "brief missing skills or risk note",
        "required_documents_checklist": "markdown checklist",
        "application_notes": "brief notes for human review before applying",
    }
    return (
        "Create GIS job application materials from this sanitized context only.\n"
        "Do not use or mention local file paths, .env files, tokens, private documents, or generated packet history.\n"
        "Return valid JSON matching this schema:\n"
        f"{json.dumps(schema, ensure_ascii=True)}\n\n"
        f"Sanitized context:\n{json.dumps(context, ensure_ascii=True)}"
    )
