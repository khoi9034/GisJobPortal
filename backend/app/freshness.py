from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import yaml

from .paths import APPLICATION_RULES_PATH

DEFAULT_FRESHNESS = {
    "max_default_age_days": 30,
    "hide_after_days": 45,
    "fresh_days": 14,
    "closing_soon_days": 7,
    "unknown_date_allowed": True,
}


def freshness_rules() -> dict[str, Any]:
    try:
        data = yaml.safe_load(APPLICATION_RULES_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    return {**DEFAULT_FRESHNESS, **(data.get("freshness") or {})}


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            pass
    for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def date_iso(value: Any) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


def today_utc() -> date:
    return datetime.now(UTC).date()


def bucket(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age <= 0:
        return "today"
    if age <= 3:
        return "1-3 days"
    if age <= 7:
        return "4-7 days"
    if age <= 14:
        return "8-14 days"
    if age <= 30:
        return "15-30 days"
    return "30+ days"


def freshness_score(job: dict[str, Any]) -> int:
    if job.get("is_closed_or_missing"):
        return -20
    age = job.get("posting_age_days")
    if age is None:
        return 0
    age = int(age)
    if age <= 3:
        return 8
    if age <= 7:
        return 5
    if age <= 14:
        return 2
    if age <= 30:
        return 0
    if age <= 45:
        return -8
    return -20


def apply_freshness(
    job: dict[str, Any],
    checked_at: Any | None = None,
    first_seen_at: Any | None = None,
    rules: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    rules = rules or freshness_rules()
    today = today or today_utc()
    checked = date_iso(checked_at or job.get("last_checked_at") or job.get("last_seen_at")) or today.isoformat()
    posted = date_iso(job.get("source_posted_at") or job.get("date_posted"))
    updated = date_iso(job.get("source_updated_at"))
    closes = date_iso(job.get("source_closes_at"))
    first_seen = date_iso(first_seen_at or job.get("first_seen_at") or job.get("date_found")) or checked
    basis = parse_date(posted) or parse_date(first_seen)
    age = (today - basis).days if basis else None
    confidence = job.get("freshness_confidence") or (
        "source_posted_date" if posted else "source_updated_date" if updated else "first_seen_only" if first_seen else "unknown"
    )
    close_date = parse_date(closes)
    close_days = (close_date - today).days if close_date else None

    return {
        **job,
        "date_posted": posted or job.get("date_posted", ""),
        "date_found": job.get("date_found") or first_seen,
        "source_posted_at": posted,
        "source_updated_at": updated,
        "source_closes_at": closes,
        "first_seen_at": first_seen,
        "last_seen_at": checked,
        "last_checked_at": checked,
        "posting_age_days": age,
        "freshness_bucket": bucket(age),
        "freshness_confidence": confidence,
        "close_days_remaining": close_days,
        "is_stale": bool(age is not None and age > int(rules["max_default_age_days"])),
        "is_closed_or_missing": bool(job.get("is_closed_or_missing") or (close_date and close_date < today)),
    }
