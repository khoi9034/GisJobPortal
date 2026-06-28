from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.scoring import score_band  # noqa: E402


def score_distribution(jobs: list[dict[str, Any]]) -> Counter[str]:
    return Counter(score_band(int(job.get("match_score") or 0)) for job in jobs)


def print_job(row: dict[str, Any]) -> None:
    close_days = row.get("close_days_remaining")
    print(
        f"- {row.get('match_score'):>3} {row.get('score_band') or score_band(int(row.get('match_score') or 0))}: "
        f"{row.get('title')} | {row.get('company')} | {row.get('source')} | "
        f"posted {row.get('source_posted_at') or row.get('date_posted') or 'unknown'} | "
        f"closes {row.get('source_closes_at') or 'unknown'}"
        f"{f' ({close_days} days)' if isinstance(close_days, int) else ''}"
    )


def main() -> int:
    jobs = db.list_jobs()
    active = db.list_jobs(active_only=True)
    if not jobs:
        print("No jobs found. Run python scripts/refresh_jobs.py first.")
        return 1

    print("total jobs by source")
    for source, count in Counter(job.get("source") or "unknown" for job in jobs).most_common():
        print(f"- {source}: {count}")

    print("\nscore distribution")
    dist = score_distribution(active)
    for band in ["excellent fit", "strong fit", "possible fit", "weak/maybe", "low fit"]:
        print(f"- {band}: {dist.get(band, 0)}")

    print("\ntop 10 jobs by score")
    for job in sorted(active, key=lambda row: int(row.get("match_score") or 0), reverse=True)[:10]:
        print_job(job)

    print("\ntop 10 jobs by freshness + closing soon")
    fresh_rows = sorted(
        active,
        key=lambda row: (
            row.get("posting_age_days") if row.get("posting_age_days") is not None else 9999,
            row.get("close_days_remaining") if row.get("close_days_remaining") is not None and row.get("close_days_remaining") >= 0 else 9999,
            -int(row.get("match_score") or 0),
        ),
    )
    for job in fresh_rows[:10]:
        print_job(job)

    positives = Counter(match for job in active for match in (job.get("positive_matches") or job.get("keyword_matches") or []))
    missing = Counter(match for job in active for match in (job.get("missing_skills") or []))
    penalties = Counter(match for job in active for match in (job.get("penalty_matches") or []))
    print("\ncommon positive keyword hits")
    for keyword, count in positives.most_common(15):
        print(f"- {keyword}: {count}")
    print("\ncommon missing keywords")
    for keyword, count in missing.most_common(10):
        print(f"- {keyword}: {count}")
    if not missing:
        print("- none")
    print("\ncommon penalty triggers")
    for keyword, count in penalties.most_common(10):
        print(f"- {keyword}: {count}")
    if not penalties:
        print("- none")

    usajobs = [job for job in active if job.get("source") == "USAJobs API"]
    strong_usajobs = [job for job in usajobs if int(job.get("match_score") or 0) >= 70]
    print("\nwhy USAJobs jobs are or are not above 70")
    if strong_usajobs:
        print(f"- {len(strong_usajobs)} active USAJobs job(s) are now 70+ after calibration.")
    else:
        print("- No active USAJobs job is 70+. Top blockers:")
    blockers = Counter()
    for job in usajobs:
        breakdown = job.get("scoring_breakdown") or {}
        if not any(word in (job.get("title") or "").lower() for word in ["gis", "geospatial", "spatial", "cartographer", "geographer", "planner"]):
            blockers["weak title match"] += 1
        if (breakdown.get("gis_relevance") or 0) < 9:
            blockers["few GIS/geospatial keywords"] += 1
        if (breakdown.get("arcgis_relevance") or 0) < 9:
            blockers["few ArcGIS keywords"] += 1
        if job.get("penalty_matches"):
            blockers["seniority/credential penalty"] += 1
    for blocker, count in blockers.most_common(5):
        print(f"- {blocker}: {count}")

    print("\nrecommended scoring/search adjustments")
    print("- Keep 70+ as strong fit; 75 was too strict for real federal descriptions.")
    print("- Keep title match strong, but require GIS/planning/spatial wording so generic technician jobs stay low.")
    print("- Keep DatePosted at 30 days or less; add more specific USAJobs terms before adding more sources.")
    print("- Review penalties after a few real applications; GS-11+ may still be too senior for first-pass applications.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
