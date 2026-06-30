from __future__ import annotations

import re
import sys
from statistics import mean
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402


def safe_print(text: str = "") -> None:
    print(str(text).encode("ascii", errors="replace").decode("ascii"))


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
        missing_links = sum(1 for job in source_jobs if not (job.get("apply_url") or job.get("source_url")))
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
                "missing_links": missing_links,
                "source_errors": errors,
                "recommendation": recommendation(len(source_jobs), strong, low, errors, bool(source.get("enabled", True))),
            }
        )
    return output


def main() -> int:
    safe_print("source quality")
    for row in rows():
        safe_print(
            f"- {row['source']}: total={row['total']} strong={row['strong_excellent']} "
            f"possible={row['possible']} low={row['low_fit']} avg={row['average_score']} "
            f"duplicate_rate={row['duplicate_rate']}% missing_links={row['missing_links']} recommendation={row['recommendation']}"
            + (f" errors={row['source_errors']}" if row["source_errors"] else "")
        )
    jsearch_jobs = [job for job in db.list_jobs(include_sample=False) if "jsearch" in f"{job.get('source', '')} {job.get('attribution_note', '')}".lower()]
    if jsearch_jobs:
        safe_print("\njsearch details")
        safe_print(f"- total={len(jsearch_jobs)} missing_links={sum(1 for job in jsearch_jobs if not (job.get('apply_url') or job.get('source_url')))}")
        regions: dict[str, int] = {}
        for job in jsearch_jobs:
            key = job.get("country") or job.get("region") or "unknown"
            regions[key] = regions.get(key, 0) + 1
        safe_print("- top regions: " + ", ".join(f"{name}={count}" for name, count in sorted(regions.items(), key=lambda item: item[1], reverse=True)[:10]))
        for job in sorted(jsearch_jobs, key=lambda item: int(item.get("match_score") or 0), reverse=True)[:10]:
            safe_print(f"  - {job.get('match_score')} {job.get('title')} at {job.get('company')} ({job.get('location')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
