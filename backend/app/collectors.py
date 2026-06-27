from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from . import db
from .paths import ROOT, SAMPLE_JOBS_PATH, load_backend_env
from .profile import load_profile
from .scoring import score_job
from .sources import load_sources

USAJOBS_SEARCH_TERMS = [
    "GIS Analyst",
    "GIS Technician",
    "Geospatial Analyst",
    "Urban Planning Analyst",
    "Planning Technician",
    "Spatial Analyst",
    "Transportation Planning Analyst",
]


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


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def normalize_usajobs_item(item: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    data = item.get("MatchedObjectDescriptor", item)
    details = data.get("UserArea", {}).get("Details", {})
    salary = (data.get("PositionRemuneration") or [{}])[0]
    apply_urls = data.get("ApplyURI") or []
    description = "\n\n".join(filter(None, [details.get("JobSummary"), details.get("MajorDuties")]))
    requirements = "\n\n".join(
        filter(None, [details.get("Requirements"), data.get("QualificationSummary"), details.get("Education")])
    )
    remote = "remote" if str(details.get("RemoteIndicator", "")).lower() == "true" else ""
    return normalize_job(
        {
            "title": data.get("PositionTitle", ""),
            "company": data.get("OrganizationName", ""),
            "location": data.get("PositionLocationDisplay", ""),
            "remote_status": remote,
            "source_url": data.get("PositionURI", ""),
            "apply_url": apply_urls[0] if apply_urls else data.get("PositionURI", ""),
            "description": description,
            "requirements": requirements,
            "salary_min": _as_float(salary.get("MinimumRange")),
            "salary_max": _as_float(salary.get("MaximumRange")),
            "date_posted": data.get("PublicationStartDate", ""),
        },
        source,
    )


def fetch_usajobs(term: str, source: dict[str, Any]) -> dict[str, Any]:
    load_backend_env()
    api_key = os.getenv("USAJOBS_API_KEY", "")
    user_agent = os.getenv("USAJOBS_USER_AGENT", "")
    if not api_key or not user_agent or api_key.lower().startswith("replace_") or user_agent == "your_email@example.com":
        raise RuntimeError("USAJobs credentials missing; set USAJOBS_USER_AGENT and USAJOBS_API_KEY in backend/.env")

    params = {
        "Keyword": term,
        "ResultsPerPage": str(source.get("results_per_page", 10)),
        "Fields": "Full",
        "WhoMayApply": "public",
    }
    if source.get("location"):
        params["LocationName"] = source["location"]
    url = f"{source['url']}?{parse.urlencode(params)}"
    req = request.Request(
        url,
        headers={
            "Host": "data.usajobs.gov",
            "User-Agent": user_agent,
            "Authorization-Key": api_key,
        },
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"USAJobs request failed: {getattr(exc, 'reason', exc)}") from exc


def collect_usajobs(source: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for term in source.get("search_terms") or USAJOBS_SEARCH_TERMS:
        data = fetch_usajobs(term, source)
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        jobs.extend(normalize_usajobs_item(item, source) for item in items)
    return jobs


def collect_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not source.get("enabled", True):
        return []
    if source["type"] == "manual":
        path = Path(source["url"])
        if not path.is_absolute():
            path = ROOT / path
        with open(path if path.exists() else SAMPLE_JOBS_PATH, "r", encoding="utf-8") as handle:
            return [normalize_job(item, source) for item in json.load(handle)]
    if source["type"] == "api" and source["name"].lower().startswith("usajobs"):
        return collect_usajobs(source)
    return []


def refresh_jobs(db_path: Path | str = db.DB_PATH, sources_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    profile = load_profile()
    sources = sources_override or load_sources()
    db.init_db(db_path)
    for source in sources:
        db.upsert_source(source, db_path)

    new_jobs = duplicates = jobs_collected = jobs_scored = sources_checked = sources_skipped = 0
    bands = {"high_matches": 0, "medium_matches": 0, "low_matches": 0}
    errors: dict[str, str] = {}
    for source in sources:
        if not source.get("enabled", True):
            sources_skipped += 1
            db.mark_source_checked(source["name"], "disabled", db_path)
            continue
        sources_checked += 1
        try:
            collected = collect_from_source(source)
        except Exception as exc:  # Keep one bad source from killing the whole refresh.
            message = str(exc)
            errors[source["name"]] = message
            db.mark_source_checked(source["name"], f"error: {message}", db_path)
            continue
        jobs_collected += len(collected)
        inserted = source_duplicates = 0
        for job in collected:
            scored = {**job, **score_job(job, profile)}
            jobs_scored += 1
            job_id, duplicate = db.insert_job(scored, db_path)
            if duplicate:
                duplicates += 1
                source_duplicates += 1
                continue
            new_jobs += 1
            inserted += 1
            score = scored["match_score"]
            if score >= 75:
                bands["high_matches"] += 1
            elif score >= 50:
                bands["medium_matches"] += 1
            else:
                bands["low_matches"] += 1
        db.mark_source_checked(source["name"], f"ok: {inserted} new, {source_duplicates} duplicates", db_path)

    return {
        "sources_checked": sources_checked,
        "sources_skipped": sources_skipped,
        "jobs_collected": jobs_collected,
        "jobs_scored": jobs_scored,
        "new_jobs_found": new_jobs,
        "duplicates_skipped": duplicates,
        "errors": errors,
        **bands,
    }
