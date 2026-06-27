from __future__ import annotations

import json
import os
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from . import db
from .freshness import apply_freshness
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


def plain_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(str(value or "")))).strip()


def normalize_job(raw: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    location = (raw.get("location") or "Unknown").strip()
    if not title or not company:
        raise ValueError("Job requires title and company")
    source_posted_at = raw.get("source_posted_at") or raw.get("date_posted") or raw.get("posted_at", "")
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
        "date_posted": source_posted_at,
        "source_posted_at": source_posted_at,
        "source_updated_at": raw.get("source_updated_at") or raw.get("updated_at", ""),
        "source_closes_at": raw.get("source_closes_at") or raw.get("closing_at", ""),
        "freshness_confidence": raw.get("freshness_confidence", ""),
        "status": "new",
    }


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def join_text_parts(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values:
        rows = value if isinstance(value, list) else [value]
        parts.extend(plain_text(row) for row in rows if row)
    return "\n\n".join(filter(None, parts))


def normalize_usajobs_item(item: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    data = item.get("MatchedObjectDescriptor", item)
    details = data.get("UserArea", {}).get("Details", {})
    salary = (data.get("PositionRemuneration") or [{}])[0]
    apply_urls = data.get("ApplyURI") or []
    description = join_text_parts([details.get("JobSummary"), details.get("MajorDuties")])
    requirements = join_text_parts([details.get("Requirements"), data.get("QualificationSummary"), details.get("Education")])
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
            "source_posted_at": data.get("PublicationStartDate", ""),
            "source_closes_at": data.get("ApplicationCloseDate") or details.get("ApplicationCloseDate", ""),
        },
        source,
    )


def fetch_usajobs(term: str, source: dict[str, Any]) -> dict[str, Any]:
    load_backend_env()
    api_key = os.getenv("USAJOBS_AUTHORIZATION_KEY") or os.getenv("USAJOBS_API_KEY", "")
    user_agent = os.getenv("USAJOBS_USER_AGENT", "")
    if not api_key or not user_agent or api_key.lower().startswith("replace_") or user_agent == "your_email@example.com":
        raise RuntimeError("USAJobs credentials missing; set USAJOBS_USER_AGENT and USAJOBS_AUTHORIZATION_KEY in backend/.env")

    params = {
        "Keyword": term,
        "ResultsPerPage": str(source.get("results_per_page", 10)),
        "Fields": "Full",
        "WhoMayApply": "public",
        "DatePosted": str(source.get("default_date_posted_days", 30)),
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


def fetch_json(url: str) -> Any:
    try:
        with request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"request failed: {getattr(exc, 'reason', exc)}") from exc


def collect_usajobs(source: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for term in source.get("search_terms") or USAJOBS_SEARCH_TERMS:
        data = fetch_usajobs(term, source)
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        jobs.extend(normalize_usajobs_item(item, source) for item in items)
    return jobs


def board_token(source: dict[str, Any]) -> str:
    token = source.get("board_token") or str(source.get("url", "")).rstrip("/").split("/")[-1]
    if not token or token == "jobs":
        raise RuntimeError("Greenhouse source requires board_token")
    return token


def normalize_greenhouse_job(item: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    location = item.get("location") or {}
    return normalize_job(
        {
            "title": item.get("title", ""),
            "company": source.get("company") or source["name"],
            "location": location.get("name") if isinstance(location, dict) else str(location or ""),
            "source_url": item.get("absolute_url", ""),
            "apply_url": item.get("absolute_url", ""),
            "description": plain_text(item.get("content", "")),
            "source_updated_at": item.get("updated_at", ""),
            "freshness_confidence": "first_seen_only",
        },
        source,
    )


def collect_greenhouse(source: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{parse.quote(board_token(source))}/jobs?content=true"
    data = fetch_json(url)
    return [normalize_greenhouse_job(item, source) for item in data.get("jobs", [])]


def lever_site(source: dict[str, Any]) -> str:
    site = source.get("site") or str(source.get("url", "")).rstrip("/").split("/")[-1]
    if not site:
        raise RuntimeError("Lever source requires site")
    return site


def normalize_lever_job(item: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    categories = item.get("categories") or {}
    lists = "\n".join(plain_text(part.get("content", "")) for part in item.get("lists", []) if isinstance(part, dict))
    description = "\n\n".join(
        filter(None, [plain_text(item.get("descriptionPlain") or item.get("description")), lists, plain_text(item.get("additionalPlain"))])
    )
    return normalize_job(
        {
            "title": item.get("text", ""),
            "company": source.get("company") or source["name"],
            "location": categories.get("location", ""),
            "remote_status": categories.get("workplaceType", ""),
            "source_url": item.get("hostedUrl", ""),
            "apply_url": item.get("applyUrl") or item.get("hostedUrl", ""),
            "description": description,
            "requirements": plain_text(item.get("additionalPlain", "")),
            "freshness_confidence": "first_seen_only",
        },
        source,
    )


def collect_lever(source: dict[str, Any]) -> list[dict[str, Any]]:
    site = parse.quote(lever_site(source))
    data = fetch_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
    if not isinstance(data, list):
        raise RuntimeError("Lever response was not a job list")
    return [normalize_lever_job(item, source) for item in data]


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
    if source["type"] == "greenhouse":
        return collect_greenhouse(source)
    if source["type"] == "lever":
        return collect_lever(source)
    return []


def refresh_jobs(db_path: Path | str = db.DB_PATH, sources_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    profile = load_profile()
    sources = sources_override or load_sources()
    db.init_db(db_path)
    for source in sources:
        db.upsert_source(source, db_path)

    new_jobs = duplicates = jobs_collected = jobs_scored = sources_checked = sources_skipped = marked_missing = 0
    errors: dict[str, str] = {}
    source_results: list[dict[str, Any]] = []
    for source in sources:
        if not source.get("enabled", True):
            sources_skipped += 1
            db.mark_source_checked(source["name"], "disabled", db_path, jobs_found=0)
            continue
        sources_checked += 1
        checked_at = db.now_iso()
        try:
            collected = collect_from_source(source)
        except Exception as exc:  # Keep one bad source from killing the whole refresh.
            message = str(exc)
            errors[source["name"]] = message
            db.mark_source_checked(source["name"], f"error: {message}", db_path, jobs_found=0, error=message)
            source_results.append({"name": source["name"], "collected": 0, "inserted": 0, "duplicates": 0, "error": message})
            continue
        jobs_collected += len(collected)
        inserted = source_duplicates = source_closed = 0
        for job in collected:
            freshened = apply_freshness(job, checked_at=checked_at)
            scored = {**freshened, **score_job(freshened, profile)}
            jobs_scored += 1
            if scored.get("is_closed_or_missing"):
                source_closed += 1
            job_id, duplicate = db.insert_job(scored, db_path)
            if duplicate:
                duplicates += 1
                source_duplicates += 1
                continue
            new_jobs += 1
            inserted += 1
        marked_missing += source_closed + db.mark_missing_jobs(source["name"], checked_at, collected, db_path)
        db.mark_source_checked(
            source["name"],
            f"ok: {inserted} new, {source_duplicates} duplicates",
            db_path,
            jobs_found=len(collected),
        )
        source_results.append(
            {"name": source["name"], "collected": len(collected), "inserted": inserted, "duplicates": source_duplicates, "error": ""}
        )

    counts = db.freshness_counts(db_path)
    active_jobs = db.list_jobs(path=db_path, active_only=True)
    bands = {
        "high_matches": sum(1 for item in active_jobs if item["match_score"] >= 75),
        "medium_matches": sum(1 for item in active_jobs if 50 <= item["match_score"] < 75),
        "low_matches": sum(1 for item in active_jobs if item["match_score"] < 50),
    }
    return {
        "sources_checked": sources_checked,
        "sources_skipped": sources_skipped,
        "jobs_collected": jobs_collected,
        "jobs_scored": jobs_scored,
        "new_jobs_found": new_jobs,
        "new_jobs_inserted": new_jobs,
        "duplicates_skipped": duplicates,
        "duplicates_updated": duplicates,
        "jobs_marked_missing_or_closed": marked_missing,
        "errors": errors,
        "source_results": source_results,
        **db.review_counts(db_path),
        **counts,
        **bands,
    }
