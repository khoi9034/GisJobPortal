from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.documents import generate_application_packet, get_application_packet  # noqa: E402
from backend.app.profile import load_profile  # noqa: E402
from backend.app.reports import redact  # noqa: E402
from backend.app.scoring import score_band  # noqa: E402
from scripts.qa_application_packet import quality_checks  # noqa: E402


def safe_print(text: str = "") -> None:
    value = redact(text).replace(str(ROOT / "private"), "[private]").replace("private\\", "[private]\\").replace("private/", "[private]/")
    print(value.encode("ascii", errors="replace").decode("ascii"))


def packet_for(job: dict[str, Any]) -> tuple[dict[str, Any], str]:
    packet = get_application_packet(job["id"])
    if packet.get("exists"):
        return packet, "existing"
    return generate_application_packet(job["id"]), "generated"


def qa_job(job: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not (job.get("apply_url") or job.get("source_url")):
        warnings.append("missing apply/source link")
    if not (job.get("score_band") or score_band(int(job.get("match_score") or 0))):
        warnings.append("missing score band")
    try:
        packet, mode = packet_for(job)
    except Exception as exc:  # packet QA should keep checking the rest
        return [*warnings, f"packet generation failed: {exc}"]
    files = packet.get("files", {})
    warnings.extend(quality_checks(job, packet, profile))
    summary = files.get("job_summary.md", "")
    if (job.get("apply_url") or job.get("source_url")) and not any(link and link in summary for link in [job.get("apply_url"), job.get("source_url")]):
        warnings.append("job_summary missing apply/source link")
    safe_print(f"- {job['id']} | {job['match_score']} | {job['title']} | packet {mode} | {'ok' if not warnings else 'warn'}")
    for warning in warnings:
        safe_print(f"  - {warning}")
    return warnings


def main() -> int:
    os.environ["OPENROUTER_API_KEY"] = ""
    jobs = db.apply_today(limit=5, include_sample=False)
    if not jobs:
        safe_print("No Apply Today jobs found.")
        return 1
    profile = load_profile()
    safe_print("Apply Today QA")
    all_warnings: list[str] = []
    for job in jobs:
        all_warnings.extend(qa_job(job, profile))
    safe_print(f"Summary: {len(jobs)} jobs checked, {len(all_warnings)} warnings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
