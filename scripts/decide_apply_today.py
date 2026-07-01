from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.profile import load_profile  # noqa: E402
from backend.app.reports import redact  # noqa: E402
from scripts.qa_application_packet import quality_checks  # noqa: E402
from scripts.qa_apply_today import packet_for  # noqa: E402


def safe_print(text: str = "") -> None:
    print(redact(text).replace(str(ROOT / "private"), "[private]").encode("ascii", errors="replace").decode("ascii"))


def decide_job(row: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    job = {**(db.get_job(row["id"]) or {}), **row}
    try:
        packet, mode = packet_for(job)
        warnings = quality_checks(job, packet, profile)
    except Exception as exc:
        packet, mode, warnings = {}, "error", [f"packet QA failed: {exc}"]
    job = {**job, **(db.get_job(row["id"]) or {})}
    decision = db.application_decision(job)
    if warnings and decision["application_priority"] == "apply_now":
        decision = {**decision, "application_priority": "review_first", "next_action": "Fix packet QA warnings, then apply manually."}
    return {**job, **decision, "packet_qa_mode": mode, "packet_qa_warnings": warnings}


def main() -> int:
    os.environ["OPENROUTER_API_KEY"] = ""
    jobs = db.apply_today(limit=5, include_sample=False)
    if not jobs:
        safe_print("No Apply Today jobs found.")
        return 1
    profile = load_profile()
    safe_print("Apply Today Decisions")
    for row in jobs:
        job = decide_job(row, profile)
        blockers = ", ".join([*job.get("application_blockers", []), *job.get("packet_qa_warnings", [])]) or "none"
        safe_print(f"- {job['application_priority']} | {job['match_score']} | {job['title']} | {job['company']}")
        safe_print(f"  reason: {job['application_priority_reason']}")
        safe_print(f"  blockers: {blockers}")
        safe_print(f"  next: {job['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
