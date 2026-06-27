from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.collectors import refresh_jobs  # noqa: E402


if __name__ == "__main__":
    result = refresh_jobs()
    print(f"sources checked: {result['sources_checked']}")
    print(f"sources skipped/disabled: {result['sources_skipped']}")
    print(f"jobs collected: {result['jobs_collected']}")
    print(f"new jobs found: {result['new_jobs_found']}")
    print(f"duplicates skipped: {result['duplicates_skipped']}")
    print(f"jobs scored: {result['jobs_scored']}")
    print(f"high matches above 75: {result['high_matches']}")
    print(f"medium matches 50-74: {result['medium_matches']}")
    print(f"low matches below 50: {result['low_matches']}")
    if result["errors"]:
        print("errors:")
        for source, message in result["errors"].items():
            print(f"- {source}: {message}")
    else:
        print("errors: none")
