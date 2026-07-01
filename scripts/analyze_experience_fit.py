from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.scoring import analyze_experience, score_band  # noqa: E402


def safe_print(text: str = "") -> None:
    print(str(text).encode("ascii", errors="replace").decode("ascii"))


def experience(job: dict) -> dict:
    parsed = analyze_experience(job)
    stored = {key: job.get(key) for key in parsed if job.get(key) not in (None, "", [])}
    if stored.get("experience_fit") == "unknown":
        stored.pop("experience_fit")
    return {**parsed, **stored}


def main() -> int:
    jobs = db.list_jobs(include_sample=False)
    rows = [{**job, **experience(job)} for job in jobs]
    detected = [job for job in rows if job.get("required_experience_years")]
    over_cap = [job for job in rows if (job.get("required_experience_years") or 0) > 5 or job.get("experience_fit") in {"over_cap", "too_senior"}]
    risky_high = [job for job in over_cap if int(job.get("match_score") or 0) >= 70]
    safe_top = [job for job in sorted(rows, key=lambda item: int(item.get("match_score") or 0), reverse=True) if job_safe(job)][:10]
    safe_print("experience fit")
    safe_print(f"- jobs with required years detected: {len(detected)}")
    safe_print(f"- jobs over 5 years or too senior: {len(over_cap)}")
    safe_print(f"- high-scoring over-cap jobs: {len(risky_high)}")
    for job in risky_high[:10]:
        safe_print(f"  - {job.get('match_score')} {job.get('title')} at {job.get('company')} | required={job.get('required_experience_years')} fit={job.get('experience_fit')} | {job.get('experience_blocker_reason') or 'evidence missing'}")
    safe_print("- top jobs after experience cap:")
    for job in safe_top:
        safe_print(f"  - {job.get('match_score')} {score_band(int(job.get('match_score') or 0))}: {job.get('title')} at {job.get('company')} | fit={job.get('experience_fit') or 'unknown'}")
    safe_print("- recommendation: rescore/refresh after deploy so over-cap jobs get capped before ranking.")
    return 0


def job_safe(job: dict) -> bool:
    years = job.get("required_experience_years") or 0
    return years <= 5 and job.get("experience_fit") not in {"over_cap", "too_senior"}


if __name__ == "__main__":
    raise SystemExit(main())
