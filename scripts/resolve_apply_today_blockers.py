from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.reports import redact  # noqa: E402


def safe_print(text: str = "") -> None:
    print(redact(text).replace(str(ROOT / "private"), "[private]").encode("ascii", errors="replace").decode("ascii"))


def main() -> int:
    rows = db.apply_today(limit=5, include_sample=False)
    if not rows:
        safe_print("No Apply Today jobs found.")
        return 1
    safe_print("Apply Today Blocker Resolver (dry run)")
    for row in rows:
        status = db.job_blockers(row["id"])
        safe_print(f"- {status['application_priority']} | {row['match_score']} | {row['title']} | {row['company']}")
        for blocker in status.get("blockers", []):
            if blocker.get("resolved"):
                continue
            safe_print(f"  - {blocker['severity']} {blocker['blocker_type']} from {blocker['source_field']}: {blocker['evidence_text']}")
        safe_print(f"  next: {status['next_action']}")
    safe_print("Dry run only. Use the dashboard buttons to clear, mark not applicable, or override.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
