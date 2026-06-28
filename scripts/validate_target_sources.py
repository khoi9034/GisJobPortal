from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.source_validation import validate_source  # noqa: E402
from backend.app.sources import load_sources  # noqa: E402

SAFE_ENABLED_TYPES = {"api", "greenhouse", "lever", "manual"}


def target_sources() -> list[dict]:
    return [
        source for source in load_sources()
        if source.get("enabled") and source.get("type") in SAFE_ENABLED_TYPES
    ]


def main() -> int:
    rows = []
    for source in target_sources():
        row = validate_source(source)
        db.record_source_validation(source, row)
        rows.append(row)
        error = f" | error: {row['last_error']}" if row.get("last_error") else ""
        print(f"{row['name']} [{row['type']}]: {row['validation_status']} | sampled {row['jobs_sampled']} | found {row['jobs_found_last_run']}{error}")
    if not rows:
        print("No enabled safe target sources to validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
