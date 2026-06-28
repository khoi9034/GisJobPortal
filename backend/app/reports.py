from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import REPORTS_DIR

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")


def redact(text: Any) -> str:
    value = str(text)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            value = value.replace(secret, "[redacted]")
    return value


def close_days(job: dict[str, Any]) -> int | None:
    value = job.get("close_days_remaining")
    return value if isinstance(value, int) else None


def recommend_reason(job: dict[str, Any]) -> str:
    days = close_days(job)
    if days is not None and 0 <= days <= 7:
        return f"Closing in {days} days"
    if int(job.get("match_score") or 0) >= 70:
        return job.get("score_band") or "Strong match score"
    if (job.get("posting_age_days") or 99) <= 14:
        return "Fresh posting"
    return "Needs review"


def top_recommended_jobs(jobs: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    rows = [job for job in jobs if not job.get("is_closed_or_missing") and not job.get("is_stale") and (job.get("review_status") or "unreviewed") == "unreviewed"]
    return sorted(rows, key=lambda job: (-int(job.get("match_score") or 0), close_days(job) if close_days(job) is not None and close_days(job) >= 0 else 9999, int(job.get("posting_age_days") or 9999)))[:limit]


def summary_counts(result: dict[str, Any]) -> dict[str, int]:
    keys = [
        "sources_checked",
        "jobs_collected",
        "new_jobs_inserted",
        "duplicates_updated",
        "unreviewed_jobs",
        "high_match_unreviewed_jobs",
        "closing_soon_jobs",
        "fresh_jobs",
        "stale_jobs",
        "packets_ready",
        "applied_followups_needed",
    ]
    return {key: int(result.get(key) or 0) for key in keys}


def write_daily_report(result: dict[str, Any], jobs: list[dict[str, Any]], report_dir: Path = REPORTS_DIR) -> Path:
    now = datetime.now(UTC)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"daily_review_{now.date().isoformat()}.md"
    counts = summary_counts(result)
    errors = result.get("errors") or {}
    lines = [
        f"# Daily Review Digest - {now.date().isoformat()}",
        "",
        f"Refresh timestamp: {now.isoformat()}",
        "",
        "## Summary",
    ]
    labels = {
        "sources_checked": "Sources checked",
        "jobs_collected": "Jobs collected",
        "new_jobs_inserted": "New jobs inserted",
        "duplicates_updated": "Duplicates updated",
        "unreviewed_jobs": "Unreviewed jobs",
        "high_match_unreviewed_jobs": "High match unreviewed jobs",
        "closing_soon_jobs": "Closing soon jobs",
        "fresh_jobs": "Fresh jobs",
        "stale_jobs": "Stale jobs",
        "packets_ready": "Packet ready jobs",
        "applied_followups_needed": "Applied follow-up jobs",
    }
    lines.extend(f"- {label}: {counts[key]}" for key, label in labels.items())
    lines.append(f"- Source errors: {len(errors)}")
    if errors:
        lines.extend(f"  - {redact(source)}: {redact(message)}" for source, message in errors.items())
    else:
        lines.append("  - none")
    lines.extend(["", "## Top 10 Recommended Jobs"])
    for index, job in enumerate(top_recommended_jobs(jobs), 1):
        lines.extend(
            [
                f"{index}. {job.get('title')} - {job.get('company')}",
                f"   - Location: {job.get('location')}",
                f"   - Match score: {job.get('match_score')}",
                f"   - Score band: {job.get('score_band') or 'unknown'}",
                f"   - Posted date: {job.get('source_posted_at') or job.get('date_posted') or 'unknown'}",
                f"   - Close date: {job.get('source_closes_at') or 'unknown'}",
                f"   - Days until close: {close_days(job) if close_days(job) is not None else 'unknown'}",
                f"   - Source: {job.get('source')}",
                f"   - Apply URL: {job.get('apply_url')}",
                f"   - Recommended because: {recommend_reason(job)}",
            ]
        )
    if not top_recommended_jobs(jobs):
        lines.append("No active unreviewed jobs to recommend.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_summary(text: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"- ([A-Za-z ]+): (\d+)$", line.strip())
        if match:
            summary[match.group(1).lower().replace(" ", "_")] = int(match.group(2))
    return summary


def latest_report(report_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    reports = sorted(report_dir.glob("daily_review_*.md")) if report_dir.exists() else []
    if not reports:
        return {"exists": False, "date": "", "text": "No daily review report has been generated yet.", "summary": {}}
    path = reports[-1]
    text = path.read_text(encoding="utf-8")
    date = path.stem.removeprefix("daily_review_")
    return {"exists": True, "date": date, "path": str(path), "text": text, "summary": parse_summary(text)}
