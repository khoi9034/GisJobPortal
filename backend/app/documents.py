from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import db
from .materials import generate_materials
from .paths import (
    APPLICATION_PACKETS_DIR,
    APPLICATION_RULES_PATH,
    RESUME_DIR,
    RESUME_EXTRACTED_PATH,
    TRANSCRIPT_DIR,
    TRANSCRIPT_SUMMARY_PATH,
)
from .profile import load_profile

TRANSCRIPT_PHRASES = {
    "transcript required",
    "unofficial transcript",
    "official transcript",
    "academic transcript",
    "college transcript",
    "coursework",
    "gpa",
    "degree verification",
}

ACADEMIC_KEYWORDS = {
    "geography",
    "gis",
    "geographic",
    "spatial",
    "planning",
    "urban",
    "statistics",
    "python",
    "database",
    "cartography",
    "remote sensing",
    "course",
    "degree",
    "gpa",
}


def load_application_rules(path: Path | str = APPLICATION_RULES_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def first_pdf(folder: Path) -> Path:
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF found in {folder}")
    return pdfs[0]


def read_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf to extract PDF text") from exc

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_resume(resume_dir: Path = RESUME_DIR, output_path: Path = RESUME_EXTRACTED_PATH) -> dict[str, Any]:
    pdf = first_pdf(resume_dir)
    text = read_pdf_text(pdf)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"# Resume Extracted\n\n{text}\n", encoding="utf-8")
    return {"pdf": str(pdf), "output": str(output_path), "characters": len(text)}


def summarize_transcript_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = []
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in ACADEMIC_KEYWORDS):
            useful.append(line)
    # ponytail: keyword summary keeps transcript extraction local and small; add a parser if transcript formats need precision.
    body = "\n".join(dict.fromkeys(useful[:80])) or "No GIS, planning, degree, GPA, or coursework lines were detected."
    return f"# Transcript Summary\n\n{body}\n"


def extract_transcript(
    transcript_dir: Path = TRANSCRIPT_DIR,
    output_path: Path = TRANSCRIPT_SUMMARY_PATH,
) -> dict[str, Any]:
    pdf = first_pdf(transcript_dir)
    text = read_pdf_text(pdf)
    summary = summarize_transcript_text(text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary, encoding="utf-8")
    return {"pdf": str(pdf), "output": str(output_path), "characters": len(summary)}


def resume_summary(path: Path = RESUME_EXTRACTED_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "text": ""}
    return {"exists": True, "path": str(path), "text": path.read_text(encoding="utf-8")}


def transcript_summary(path: Path = TRANSCRIPT_SUMMARY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "text": ""}
    return {"exists": True, "path": str(path), "text": path.read_text(encoding="utf-8")}


def job_text(job: dict[str, Any]) -> str:
    return " ".join(str(job.get(key, "")) for key in ["title", "company", "location", "description", "requirements"]).lower()


def should_use_transcript(job: dict[str, Any]) -> bool:
    text = job_text(job)
    if any(phrase in text for phrase in TRANSCRIPT_PHRASES):
        return True
    academic = any(word in text for word in ["coursework", "degree", "gpa", "academic background"])
    internship_or_public = any(word in text for word in ["intern", "internship", "government", "county", "city"])
    entry = any(word in text for word in ["entry-level", "entry level", "technician"])
    return academic and (internship_or_public or entry)


def detect_document_checklist(job: dict[str, Any]) -> dict[str, Any]:
    text = job_text(job)
    return {
        "resume_required": True,
        "cover_letter_required": any(phrase in text for phrase in ["cover letter", "letter of interest"]),
        "transcript_required": any(phrase in text for phrase in TRANSCRIPT_PHRASES),
        "portfolio_link_included": True,
        "references_required": any(phrase in text for phrase in ["references", "reference list"]),
        "writing_sample_required": "writing sample" in text,
        "other_documents": "Review the posting for portal-specific uploads." if any(word in text for word in ["attach", "upload", "documents"]) else "",
    }


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "job"


def packet_dir_for(job: dict[str, Any]) -> Path:
    return APPLICATION_PACKETS_DIR / f"job-{job['id']}-{safe_slug(job['company'])}-{safe_slug(job['title'])}"


def checklist_markdown(checklist: dict[str, Any]) -> str:
    labels = {
        "resume_required": "Resume required",
        "cover_letter_required": "Cover letter required",
        "transcript_required": "Transcript required",
        "portfolio_link_included": "Portfolio link included",
        "references_required": "References required",
        "writing_sample_required": "Writing sample required",
    }
    rows = [f"- [{'x' if checklist.get(key) else ' '}] {label}" for key, label in labels.items()]
    rows.append(f"- Other documents: {checklist.get('other_documents') or 'None flagged'}")
    return "# Required Documents Checklist\n\n" + "\n".join(rows) + "\n"


def build_packet_files(
    job: dict[str, Any],
    profile: dict[str, Any],
    resume_text: str,
    transcript_text: str,
    checklist: dict[str, Any],
) -> dict[str, str]:
    materials = generate_materials(job, profile, resume_text, transcript_text)
    notes = [
        "# Application Notes",
        "",
        "Review every material before submitting. This app does not auto-submit applications.",
        f"Portfolio included: {profile['portfolio']}",
        f"Resume source: {'private/resume/resume_extracted.md' if resume_text else 'config/profile.yaml fallback'}",
        f"Transcript summary used: {'yes' if transcript_text else 'no'}",
    ]
    return {
        "cover_letter.md": materials["cover_letter"],
        "followup_email.md": materials["followup_email"],
        "recruiter_message.md": materials["recruiter_message"],
        "resume_angle.md": job.get("recommended_resume_angle") or "Lead with Cabarrus County GIS, public GIS data, and ArcGIS Enterprise work.",
        "resume_bullet_suggestions.md": "# Resume Bullet Suggestions\n\n" + "\n".join(f"- {item}" for item in materials["resume_bullets"]) + "\n",
        "required_documents_checklist.md": checklist_markdown(checklist),
        "application_notes.md": "\n".join(notes) + "\n",
    }


def write_packet(packet_dir: Path, files: dict[str, str]) -> None:
    packet_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (packet_dir / name).write_text(content, encoding="utf-8")


def generate_application_packet(job_id: int) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    profile = load_profile()
    resume_text = resume_summary()["text"]
    transcript_text = transcript_summary()["text"] if should_use_transcript(job) else ""
    checklist = {**detect_document_checklist(job), **(job.get("document_checklist") or {})}
    files = build_packet_files(job, profile, resume_text, transcript_text, checklist)
    packet_dir = packet_dir_for(job)
    write_packet(packet_dir, files)
    materials = generate_materials(job, profile, resume_text, transcript_text)
    db.update_job_fields(
        job_id,
        {
            "status": "materials_generated",
            "fit_summary": materials["fit_summary"],
            "generated_cover_letter": materials["cover_letter"],
            "generated_followup_email": materials["followup_email"],
            "recruiter_message": materials["recruiter_message"],
            "resume_bullet_suggestions": materials["resume_bullets"],
            "application_packet_dir": str(packet_dir),
            "document_checklist": checklist,
        },
    )
    return {"job_id": job_id, "packet_dir": str(packet_dir), "files": files, "document_checklist": checklist}


def get_application_packet(job_id: int) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    packet_dir = Path(job.get("application_packet_dir") or packet_dir_for(job))
    files = {}
    if packet_dir.exists():
        files = {path.name: path.read_text(encoding="utf-8") for path in sorted(packet_dir.glob("*.md"))}
    return {"job_id": job_id, "exists": bool(files), "packet_dir": str(packet_dir), "files": files, "document_checklist": job.get("document_checklist") or detect_document_checklist(job)}
