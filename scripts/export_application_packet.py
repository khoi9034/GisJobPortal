from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.documents import detect_document_checklist, packet_dir_for, safe_slug  # noqa: E402
from backend.app.reports import redact  # noqa: E402

EXPORTS_DIR = ROOT / "runtime" / "exports"


def packet_files(packet_dir: Path) -> list[Path]:
    return sorted(path for path in packet_dir.glob("*.md") if path.is_file())


def safe_text(text: str) -> str:
    return redact(text).replace(str(ROOT / "private"), "[private]").replace("private\\", "[private]\\").replace("private/", "[private]/")


def job_summary(job: dict[str, Any]) -> str:
    apply_url = job.get("apply_url") or ""
    source_url = job.get("source_url") or ""
    return "\n".join(
        [
            "# Job Summary",
            "",
            f"- Title: {job.get('title')}",
            f"- Company: {job.get('company')}",
            f"- Location: {job.get('location')}",
            f"- Source: {job.get('source')}",
            f"- Match score: {job.get('match_score')}",
            f"- Score band: {job.get('score_band') or 'unknown'}",
            f"- Close date: {job.get('source_closes_at') or 'unknown'}",
            f"- Apply URL: {apply_url or 'No apply link available from source.'}",
            f"- Source URL: {source_url or 'No source link available from source.'}",
            f"- Original source: {job.get('original_source') or 'unknown'}",
            f"- Link status: {job.get('link_status') or ('available' if apply_url else 'source_only' if source_url else 'missing')}",
            "",
        ]
    )


def submission_checklist(job: dict[str, Any]) -> str:
    checklist = job.get("document_checklist") or {}
    transcript = "only if required" if checklist.get("transcript_required") else "not flagged"
    cover = "required" if checklist.get("cover_letter_required") else "recommended"
    return "\n".join(
        [
            "# Submission Checklist",
            "",
            "- [ ] Open apply link manually",
            "- [ ] Upload resume manually",
            f"- [ ] Upload cover letter manually: {cover}",
            f"- [ ] Upload transcript manually: {transcript}",
            f"- [ ] Confirm portfolio link included: {'yes' if checklist.get('portfolio_link_included') else 'check manually'}",
            f"- [ ] References: {'flagged' if checklist.get('references_required') else 'not flagged'}",
            f"- [ ] Work authorization / citizenship: {'flagged' if checklist.get('work_authorization_flag') else 'not flagged'}",
            f"- [ ] Clearance: {'flagged' if checklist.get('clearance_flag') else 'not flagged'}",
            f"- [ ] Relocation / remote notes: {checklist.get('remote_note') or ('relocation flagged' if checklist.get('relocation_flag') else 'not flagged')}",
            "- [ ] Paste/check portal answers",
            "- [ ] Submit manually outside this app",
            "- [ ] Record confirmation number",
            "- [ ] Mark applied in GIS Apply Copilot",
            "",
        ]
    )


def final_submission_checklist(job: dict[str, Any]) -> str:
    checklist = job.get("document_checklist") or {}
    return "\n".join(
        [
            "# Final Submission Checklist",
            "",
            "- [ ] Confirm job is still open",
            "- [ ] Open apply link",
            "- [ ] Upload resume",
            "- [ ] Upload cover letter if required",
            "- [ ] Upload transcript only if required",
            "- [ ] Paste portfolio link",
            "- [ ] Answer screening questions carefully",
            "- [ ] Save confirmation number",
            "- [ ] Mark applied in portal",
            "- [ ] Set follow-up date",
            f"- Transcript note: {checklist.get('transcript_review_note') or 'None'}",
            "",
        ]
    )


def export_packet(job_id: int, db_path: Path | str = db.DB_PATH, export_root: Path = EXPORTS_DIR) -> Path:
    job = db.get_job(job_id, db_path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    detected_checklist = detect_document_checklist(job)
    checklist = {**detected_checklist, **(job.get("document_checklist") or {})}
    checklist["transcript_required"] = detected_checklist["transcript_required"]
    checklist["transcript_review_note"] = detected_checklist.get("transcript_review_note", "")
    job = {**job, "document_checklist": checklist}
    packet_dir = Path(job.get("application_packet_dir") or packet_dir_for(job))
    db_files = job.get("application_packet_files_json") or {}
    files = {name: content for name, content in db_files.items() if str(name).endswith(".md")} if isinstance(db_files, dict) else {}
    file_paths = packet_files(packet_dir)
    if not files:
        files = {path.name: path.read_text(encoding="utf-8") for path in file_paths}
    if not files:
        raise FileNotFoundError(f"No generated packet found for job {job_id}. Generate the application packet first.")

    target = export_root / f"job-{job_id}-{safe_slug(job.get('company', 'company'))}-{safe_slug(job.get('title', 'job'))}"
    target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (target / name).write_text(safe_text(content), encoding="utf-8")
    (target / "job_summary.md").write_text(job_summary(job), encoding="utf-8")
    (target / "submission_checklist.md").write_text(submission_checklist(job), encoding="utf-8")
    (target / "final_submission_checklist.md").write_text(final_submission_checklist(job), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export generated application packet markdown for manual submission.")
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        path = export_packet(args.job_id)
    except (LookupError, FileNotFoundError) as exc:
        print(exc)
        return 1
    print(f"export path: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
