from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.documents import packet_dir_for, safe_slug  # noqa: E402
from backend.app.reports import redact  # noqa: E402

EXPORTS_DIR = ROOT / "runtime" / "exports"


def packet_files(packet_dir: Path) -> list[Path]:
    return sorted(path for path in packet_dir.glob("*.md") if path.is_file())


def safe_text(text: str) -> str:
    return redact(text).replace(str(ROOT / "private"), "[private]").replace("private\\", "[private]\\").replace("private/", "[private]/")


def job_summary(job: dict[str, Any]) -> str:
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
            f"- Apply URL: {job.get('apply_url')}",
            "",
        ]
    )


def submission_checklist(job: dict[str, Any]) -> str:
    checklist = job.get("document_checklist") or {}
    transcript = "only if required" if checklist.get("transcript_required") else "not flagged"
    return "\n".join(
        [
            "# Submission Checklist",
            "",
            "- [ ] Open apply link manually",
            "- [ ] Upload resume manually",
            "- [ ] Upload cover letter manually if required",
            f"- [ ] Upload transcript manually: {transcript}",
            "- [ ] Paste/check portal answers",
            "- [ ] Submit manually outside this app",
            "- [ ] Record confirmation number",
            "- [ ] Mark applied in GIS Apply Copilot",
            "",
        ]
    )


def export_packet(job_id: int, db_path: Path | str = db.DB_PATH, export_root: Path = EXPORTS_DIR) -> Path:
    job = db.get_job(job_id, db_path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    packet_dir = Path(job.get("application_packet_dir") or packet_dir_for(job))
    files = packet_files(packet_dir)
    if not files:
        raise FileNotFoundError(f"No generated packet found for job {job_id}. Generate the application packet first.")

    target = export_root / f"job-{job_id}-{safe_slug(job.get('company', 'company'))}-{safe_slug(job.get('title', 'job'))}"
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        (target / path.name).write_text(safe_text(path.read_text(encoding="utf-8")), encoding="utf-8")
    (target / "job_summary.md").write_text(job_summary(job), encoding="utf-8")
    (target / "submission_checklist.md").write_text(submission_checklist(job), encoding="utf-8")
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
