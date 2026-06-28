from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.collectors import refresh_jobs  # noqa: E402


if __name__ == "__main__":
    result = refresh_jobs()
    print("refresh summary")
    print(f"- active sources checked: {result['sources_checked']}")
    print(f"- disabled sources skipped: {result['sources_skipped']}")
    print(f"- jobs collected: {result['jobs_collected']}")
    print(f"- new jobs found: {result['new_jobs_found']}")
    print(f"- new jobs inserted: {result['new_jobs_inserted']}")
    print(f"- duplicates updated: {result['duplicates_updated']}")
    print(f"- unreviewed jobs: {result['unreviewed_jobs']}")
    print(f"- high match unreviewed jobs: {result['high_match_unreviewed_jobs']}")
    print(f"- stale jobs: {result['stale_jobs']}")
    print(f"- fresh jobs: {result['fresh_jobs']}")
    print(f"- closing soon: {result['closing_soon_jobs']}")
    print(f"- packets ready: {result['packets_ready']}")
    print(f"- applied follow-ups needed: {result['applied_followups_needed']}")
    print(f"- follow-ups due: {result.get('follow_up_due_jobs', 0)}")
    print(f"- strong/excellent matches 70+: {result['high_matches']}")
    if result["errors"]:
        print("- source errors:")
        for source, message in result["errors"].items():
            print(f"  - {source}: {message}")
    else:
        print("- source errors: none")
    print("per-source summary")
    for row in result.get("source_results", []):
        error = f", error: {row['error']}" if row["error"] else ""
        print(f"- {row['name']}: collected {row['collected']}, inserted {row['inserted']}, duplicates {row['duplicates']}{error}")
