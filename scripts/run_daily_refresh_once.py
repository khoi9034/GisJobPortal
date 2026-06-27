from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.collectors import refresh_jobs  # noqa: E402
from backend.app.reports import latest_report  # noqa: E402
from backend.app.source_validation import validate_sources  # noqa: E402


if __name__ == "__main__":
    rows = validate_sources(store=True)
    print(f"validated sources: {len(rows)}")
    result = refresh_jobs()
    report = latest_report()
    if not report["exists"]:
        raise SystemExit("daily report was not created")
    print(f"report path: {report['path']}")
    print(f"new jobs inserted: {result['new_jobs_inserted']}")
    print(f"unreviewed jobs: {result['unreviewed_jobs']}")
    print(f"high match unreviewed jobs: {result['high_match_unreviewed_jobs']}")
    print(f"closing soon jobs: {result['closing_soon_jobs']}")
    print(f"packets ready: {result['packets_ready']}")
