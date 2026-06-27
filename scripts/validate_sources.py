from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.source_validation import validate_sources  # noqa: E402


def freshness_text(row: dict) -> str:
    parts = []
    if row["supports_posted_date"]:
        parts.append("posted date")
    if row["supports_updated_date"]:
        parts.append("updated date")
    if row["supports_close_date"]:
        parts.append("close date")
    if row["first_seen_only"]:
        parts.append("first_seen fallback")
    return " + ".join(parts) if parts else "unknown"


if __name__ == "__main__":
    for row in validate_sources(store=True):
        print(f"Source: {row['name']}")
        print(f"Type: {row['type']}")
        print(f"Enabled: {str(row['enabled']).lower()}")
        print(f"Status: {row['validation_status']}")
        print(f"Valid config: {str(row['valid_config']).lower()}")
        print(f"Reachable endpoint: {str(row['reachable_endpoint']).lower()}")
        print(f"Jobs sampled: {row['jobs_sampled']}")
        print(f"Freshness: {freshness_text(row)}")
        if row["last_error"]:
            print(f"Error: {row['last_error']}")
        print()
