from __future__ import annotations

import re
import sys
from statistics import mean
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402


def duplicate_rate(source: dict, total: int) -> float:
    text = f"{source.get('last_status', '')} {source.get('errors_last_run', '')}"
    match = re.search(r"(\d+)\s+duplicates", text)
    duplicates = int(match.group(1)) if match else 0
    return round((duplicates / max(total + duplicates, 1)) * 100, 1)


def recommendation(total: int, strong: int, low: int, errors: str, enabled: bool) -> str:
    if not enabled:
        return "disabled"
    if total == 0 and "no jobs returned" in errors.lower():
        return "keep enabled as test"
    if errors:
        return "tune or disable"
    if total == 0:
        return "keep enabled as test"  # ponytail: zero-result no-key source is harmless; revisit after a week.
    if strong:
        return "keep enabled"
    if low > total / 2:
        return "tune or disable"
    return "tune"


def rows() -> list[dict]:
    jobs = db.list_jobs(include_sample=False)
    sources = {source["name"]: source for source in db.list_sources()}
    names = sorted(set(sources) | {job.get("source", "") for job in jobs if job.get("source")})
    output = []
    for name in names:
        source_jobs = [job for job in jobs if job.get("source") == name]
        scores = [int(job.get("match_score") or 0) for job in source_jobs]
        strong = sum(score >= 70 for score in scores)
        possible = sum(55 <= score < 70 for score in scores)
        low = sum(score < 55 for score in scores)
        source = sources.get(name, {})
        errors = source.get("errors_last_run") or ""
        output.append(
            {
                "source": name,
                "total": len(source_jobs),
                "strong_excellent": strong,
                "possible": possible,
                "low_fit": low,
                "average_score": round(mean(scores), 1) if scores else 0,
                "duplicate_rate": duplicate_rate(source, len(source_jobs)),
                "source_errors": errors,
                "recommendation": recommendation(len(source_jobs), strong, low, errors, bool(source.get("enabled", True))),
            }
        )
    return output


def main() -> int:
    print("source quality")
    for row in rows():
        print(
            f"- {row['source']}: total={row['total']} strong={row['strong_excellent']} "
            f"possible={row['possible']} low={row['low_fit']} avg={row['average_score']} "
            f"duplicate_rate={row['duplicate_rate']}% recommendation={row['recommendation']}"
            + (f" errors={row['source_errors']}" if row["source_errors"] else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
