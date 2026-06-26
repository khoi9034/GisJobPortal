from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import db
from .paths import ROOT, SAMPLE_JOBS_PATH
from .profile import load_profile
from .scoring import score_job
from .sources import load_sources


def normalize_job(raw: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    location = (raw.get("location") or "Unknown").strip()
    if not title or not company:
        raise ValueError("Job requires title and company")
    return {
        "title": title,
        "company": company,
        "location": location,
        "remote_status": raw.get("remote_status", ""),
        "source": raw.get("source") or source["name"],
        "source_url": raw.get("source_url") or raw.get("apply_url") or source.get("url", ""),
        "apply_url": raw.get("apply_url") or raw.get("source_url") or source.get("url", ""),
        "description": raw.get("description", ""),
        "requirements": raw.get("requirements", ""),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "date_posted": raw.get("date_posted", ""),
        "status": "new",
    }


def collect_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not source.get("enabled", True):
        return []
    if source["type"] == "manual":
        path = Path(source["url"])
        if not path.is_absolute():
            path = ROOT / path
        with open(path if path.exists() else SAMPLE_JOBS_PATH, "r", encoding="utf-8") as handle:
            return [normalize_job(item, source) for item in json.load(handle)]
    return []


def refresh_jobs(db_path: Path | str = db.DB_PATH) -> dict[str, int]:
    profile = load_profile()
    sources = load_sources()
    db.init_db(db_path)
    for source in sources:
        db.upsert_source(source, db_path)

    new_jobs = duplicates = 0
    bands = {"high_matches": 0, "medium_matches": 0, "low_matches": 0}
    for source in sources:
        for job in collect_from_source(source):
            scored = {**job, **score_job(job, profile)}
            job_id, duplicate = db.insert_job(scored, db_path)
            if duplicate:
                duplicates += 1
                continue
            new_jobs += 1
            score = scored["match_score"]
            if score >= 75:
                bands["high_matches"] += 1
            elif score >= 50:
                bands["medium_matches"] += 1
            else:
                bands["low_matches"] += 1

    return {"new_jobs_found": new_jobs, "duplicates_skipped": duplicates, **bands}

