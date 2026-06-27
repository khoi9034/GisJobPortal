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
    print(f"new jobs inserted: {result['new_jobs_inserted']}")
    print(f"duplicates skipped: {result['duplicates_skipped']}")
    print(f"duplicates updated: {result['duplicates_updated']}")
    print(f"jobs scored: {result['jobs_scored']}")
    print(f"jobs marked missing/closed: {result['jobs_marked_missing_or_closed']}")
    print(f"stale jobs count: {result['stale_jobs']}")
    print(f"fresh jobs count: {result['fresh_jobs']}")
    print(f"high matches above 75: {result['high_matches']}")
    print(f"closing soon count: {result['closing_soon_jobs']}")
    print(f"medium matches 50-74: {result['medium_matches']}")
    print(f"low matches below 50: {result['low_matches']}")
    if result["errors"]:
        print("errors:")
        for source, message in result["errors"].items():
            print(f"- {source}: {message}")
    else:
        print("errors: none")
