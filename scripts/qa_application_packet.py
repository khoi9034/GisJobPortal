from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.documents import detect_document_checklist, generate_application_packet  # noqa: E402
from backend.app.profile import load_profile  # noqa: E402

EXPECTED_FILES = {
    "cover_letter.md",
    "followup_email.md",
    "recruiter_message.md",
    "resume_angle.md",
    "resume_bullet_suggestions.md",
    "required_documents_checklist.md",
    "application_notes.md",
}


def best_job() -> dict[str, Any] | None:
    rows = [
        job for job in db.list_jobs(active_only=True)
        if job.get("source") == "USAJobs API" and not job.get("is_stale") and not job.get("is_closed_or_missing")
    ]
    rows.sort(key=lambda job: (int(job.get("match_score") or 0), job.get("source_posted_at") or job.get("first_seen_at") or ""), reverse=True)
    return rows[0] if rows else None


def quality_checks(job: dict[str, Any], packet: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    files = packet.get("files", {})
    combined = "\n".join(str(value) for value in files.values())
    cover = files.get("cover_letter.md", "")
    followup = files.get("followup_email.md", "")
    profile_has_github = "github" in json.dumps(profile).lower()
    relevant_text = " ".join(str(job.get(key, "")) for key in ["title", "description", "requirements"]).lower()
    gis_relevant = any(word in relevant_text for word in ["gis", "geospatial", "arcgis", "spatial", "planning"])
    checklist = packet.get("document_checklist") or {}
    expected_checklist = detect_document_checklist(job)

    warnings = []
    if missing := sorted(EXPECTED_FILES - set(files)):
        warnings.append(f"missing packet files: {', '.join(missing)}")
    if profile.get("portfolio", "") not in combined:
        warnings.append("portfolio link missing")
    if re.search(r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b", combined):
        warnings.append("possible phone number found")
    if "expert" in combined.lower():
        warnings.append("uses 'expert'")
    if not profile_has_github and "github" in combined.lower():
        warnings.append("mentions GitHub without profile support")
    if any(token in combined.lower() for token in ["resume_extracted.md", "transcript_summary.md", ".env", "private\\", "private/"]):
        warnings.append("raw private path or env marker found")
    if gis_relevant and "Cabarrus County" not in combined:
        warnings.append("Cabarrus County experience missing for GIS-relevant job")
    if len(followup) >= len(cover):
        warnings.append("follow-up email is not shorter than cover letter")
    if bool(checklist.get("transcript_required")) != bool(expected_checklist.get("transcript_required")):
        warnings.append("transcript checklist does not match detected requirement")
    if int(job.get("match_score") or 0) < 70:
        warnings.append("no USAJobs match above 70 found; using best current USAJobs job")
    return warnings


def main() -> int:
    os.environ["OPENROUTER_API_KEY"] = ""
    job = best_job()
    if not job:
        print("No active USAJobs job found. Run python scripts/refresh_jobs.py first.")
        return 1

    packet = generate_application_packet(job["id"])
    profile = load_profile()
    warnings = quality_checks(job, packet, profile)

    print(f"Selected job: {job['title']} | {job['company']} | {job['source']}")
    print(f"Match score: {job.get('match_score')} | posted: {job.get('source_posted_at') or 'unknown'} | closes: {job.get('source_closes_at') or 'unknown'}")
    print(f"Packet: {packet['packet_dir']}")
    print(f"Generation mode: {packet.get('generation_mode')}")
    print(f"Files: {', '.join(sorted(packet.get('files', {})))}")
    print("Quality checklist:")
    has_warning = lambda text: any(text in warning for warning in warnings)
    checks = [
        ("expected files present", not has_warning("missing packet files")),
        ("portfolio included", not has_warning("portfolio link missing")),
        ("no phone number", not has_warning("phone number")),
        ("no expert claim", not has_warning("expert")),
        ("no unsupported GitHub mention", not has_warning("GitHub")),
        ("no raw private paths", not has_warning("private path")),
        ("Cabarrus County mentioned when relevant", not has_warning("Cabarrus County")),
        ("follow-up shorter than cover letter", not has_warning("follow-up email")),
        ("transcript checklist matches posting", not has_warning("transcript checklist")),
    ]
    for label, ok in checks:
        print(f"- {label}: {'ok' if ok else 'warn'}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("Warnings: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
