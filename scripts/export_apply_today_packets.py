from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.reports import redact  # noqa: E402
from scripts.export_application_packet import EXPORTS_DIR, export_packet  # noqa: E402


def safe_print(text: str) -> None:
    print(redact(text).encode("ascii", errors="replace").decode("ascii"))


def main() -> int:
    jobs = db.apply_today(limit=5, include_sample=False)
    if not jobs:
        safe_print("No Apply Today jobs found.")
        return 1
    exported = 0
    for job in jobs:
        try:
            path = export_packet(job["id"], export_root=EXPORTS_DIR / "apply_today")
        except FileNotFoundError:
            safe_print(f"- {job['id']} {job['title']}: generate packet first")
            continue
        exported += 1
        safe_print(f"- {job['id']} {job['title']}: exported to {path}")
    safe_print(f"Exported {exported} packet(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
