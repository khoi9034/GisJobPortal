from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from . import db
from .freshness import apply_freshness
from .paths import ROOT, SAMPLE_JOBS_PATH, api_env, load_backend_env
from .profile import load_profile
from .reports import summary_counts, write_daily_report
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

BROAD_API_PROVIDERS = {"adzuna", "jsearch", "serpapi", "remotive"}
DEFAULT_BROAD_TERMS = USAJOBS_SEARCH_TERMS
EMAIL_ALERT_TYPES = {"linkedin_email_alert", "indeed_email_alert", "job_alert_email", "gmail_job_alerts"}


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
        "city": raw.get("city", ""),
        "state": raw.get("state", ""),
        "country": raw.get("country") or source.get("country", ""),
        "region": raw.get("region") or source.get("region_scope", ""),
        "international_region": raw.get("international_region") or source.get("international_region", ""),
        "work_authorization_note": raw.get("work_authorization_note", ""),
        "language_requirement": raw.get("language_requirement") or source.get("preferred_language", ""),
        "relocation_required": raw.get("relocation_required") or source.get("relocation_required", ""),
        "timezone_note": raw.get("timezone_note") or source.get("timezone_note", ""),
        "remote_status": raw.get("remote_status", ""),
        "source": raw.get("source") or source["name"],
        "source_url": raw.get("source_url", ""),
        "apply_url": raw.get("apply_url", ""),
        "external_job_id": raw.get("external_job_id", ""),
        "external_id": raw.get("external_id", ""),
        "employer_website": raw.get("employer_website", ""),
        "employer_logo": raw.get("employer_logo", ""),
        "employment_type": raw.get("employment_type", ""),
        "apply_is_direct": bool(raw.get("apply_is_direct")),
        "apply_options_json": raw.get("apply_options_json", []),
        "link_status": raw.get("link_status") or ("available" if raw.get("apply_url") else "source_only" if raw.get("source_url") else "missing"),
        "original_source": raw.get("original_source", ""),
        "attribution_note": raw.get("attribution_note", ""),
        "description": raw.get("description", ""),
        "requirements": raw.get("requirements", ""),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "latitude": _as_float(raw.get("latitude")),
        "longitude": _as_float(raw.get("longitude")),
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


def timestamp_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


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


def fetch_usajobs(term: str, source: dict[str, Any], location: str = "") -> dict[str, Any]:
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
    if location or source.get("location"):
        params["LocationName"] = location or source["location"]
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
        req = request.Request(url, headers={"User-Agent": "GisJobPortal/1.0 (+https://gis-job-portal.vercel.app)", "Accept": "application/json"})
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"request failed: {getattr(exc, 'reason', exc)}") from exc


def fetch_json_request(url: str, headers: dict[str, str] | None = None) -> Any:
    try:
        req = request.Request(url, headers={"User-Agent": "GisJobPortal/1.0 (+https://gis-job-portal.vercel.app)", "Accept": "application/json", **(headers or {})})
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"request failed: {getattr(exc, 'reason', exc)}") from exc


def collect_usajobs(source: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    locations = [""] + [str(location) for location in source.get("locations", []) if str(location).strip()]
    for term in source.get("search_terms") or USAJOBS_SEARCH_TERMS:
        for location in locations:
            data = fetch_usajobs(term, source, location)
            items = data.get("SearchResult", {}).get("SearchResultItems", [])
            jobs.extend(normalize_usajobs_item(item, source) for item in items)
    return jobs


def provider_name(source: dict[str, Any]) -> str:
    explicit = str(source.get("provider", "")).strip().lower()
    if explicit:
        return explicit
    name = str(source.get("name", "")).lower()
    return next((provider for provider in BROAD_API_PROVIDERS if provider in name), "")


def env_secret(name: str) -> str:
    load_backend_env()
    value = os.getenv(name, "").strip()
    return "" if not value or value.lower().startswith("replace_") else value


def search_terms(source: dict[str, Any]) -> list[str]:
    return [str(term) for term in source.get("search_terms", []) if str(term).strip()] or DEFAULT_BROAD_TERMS


def source_locations(source: dict[str, Any]) -> list[str]:
    return [str(item) for item in source.get("locations", []) if str(item).strip()] or [""]


def collect_adzuna(source: dict[str, Any]) -> list[dict[str, Any]]:
    app_id = env_secret("ADZUNA_APP_ID")
    app_key = env_secret("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("Adzuna credentials missing; set ADZUNA_APP_ID and ADZUNA_APP_KEY in backend/.env")
    jobs: list[dict[str, Any]] = []
    for term in search_terms(source):
        for location in source_locations(source):
            params = {"app_id": app_id, "app_key": app_key, "what": term, "content-type": "application/json"}
            if location:
                params["where"] = location
            data = fetch_json(f"{source['url']}?{parse.urlencode(params)}")
            for item in data.get("results", []):
                company = item.get("company") or {}
                location_obj = item.get("location") or {}
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("title", ""),
                            "company": company.get("display_name", "") if isinstance(company, dict) else str(company or ""),
                            "location": location_obj.get("display_name", "") if isinstance(location_obj, dict) else str(location_obj or ""),
                            "source_url": item.get("redirect_url", ""),
                            "apply_url": item.get("redirect_url", ""),
                            "description": plain_text(item.get("description", "")),
                            "salary_min": _as_float(item.get("salary_min")),
                            "salary_max": _as_float(item.get("salary_max")),
                            "source_posted_at": item.get("created", ""),
                            "external_id": item.get("id", ""),
                            "original_source": item.get("contract_type", ""),
                            "attribution_note": "Collected through Adzuna broad jobs API.",
                        },
                        source,
                    )
                )
    return jobs


def collect_jsearch(source: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = env_secret("RAPIDAPI_KEY")
    if not api_key:
        raise RuntimeError("JSearch credentials missing; set RAPIDAPI_KEY in backend/.env")
    jobs: list[dict[str, Any]] = []
    limit = int(source.get("max_jobs_per_source_per_refresh") or 0)
    host = "jsearch.p.rapidapi.com"
    for term in search_terms(source):
        query = term
        locations = source_locations(source)
        for location in locations:
            params = {"query": f"{query} {location}".strip(), "page": "1", "num_pages": "1", "date_posted": "month"}
            data = fetch_json_request(
                f"{source['url']}?{parse.urlencode(params)}",
                {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host},
            )
            for item in data.get("data", []):
                place = ", ".join(filter(None, [item.get("job_city"), item.get("job_state"), item.get("job_country")]))
                apply_options = item.get("apply_options") if isinstance(item.get("apply_options"), list) else []
                option_link = next(
                    (
                        str(option.get("apply_link") or option.get("link") or "").strip()
                        for option in apply_options
                        if isinstance(option, dict) and str(option.get("apply_link") or option.get("link") or "").strip()
                    ),
                    "",
                )
                apply_url = str(item.get("job_apply_link") or option_link or "").strip()
                source_url = str(item.get("job_google_link") or "").strip()
                employment_types = item.get("job_employment_types")
                employment_type = ", ".join(employment_types) if isinstance(employment_types, list) else item.get("job_employment_type", "")
                requirements = join_text_parts(
                    [
                        item.get("required_experience_years"),
                        item.get("education_required"),
                        item.get("required_technologies"),
                        item.get("preferred_technologies"),
                        item.get("industry"),
                        item.get("job_function"),
                    ]
                )
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("job_title", ""),
                            "company": item.get("employer_name", ""),
                            "location": place or item.get("job_location", ""),
                            "city": item.get("job_city", ""),
                            "state": item.get("job_state", ""),
                            "country": item.get("job_country", ""),
                            "remote_status": item.get("work_arrangement") or ("remote" if item.get("job_is_remote") else ""),
                            "source_url": source_url,
                            "apply_url": apply_url,
                            "link_status": "available" if apply_url else "source_only" if source_url else "missing",
                            "description": plain_text(item.get("job_description", "")),
                            "requirements": requirements,
                            "salary_min": _as_float(item.get("job_min_salary")),
                            "salary_max": _as_float(item.get("job_max_salary")),
                            "source_posted_at": item.get("job_posted_at_datetime_utc") or timestamp_iso(item.get("job_posted_at_timestamp")),
                            "external_job_id": item.get("job_id", ""),
                            "external_id": item.get("job_id", ""),
                            "employer_logo": item.get("employer_logo", ""),
                            "employer_website": item.get("employer_website", ""),
                            "employment_type": employment_type,
                            "apply_is_direct": item.get("job_apply_is_direct"),
                            "apply_options_json": apply_options,
                            "latitude": item.get("job_latitude"),
                            "longitude": item.get("job_longitude"),
                            "original_source": item.get("job_publisher", ""),
                            "work_authorization_note": "Visa sponsorship: yes" if item.get("visa_sponsorship") is True else "Visa sponsorship: no" if item.get("visa_sponsorship") is False else "",
                            "relocation_required": str(item.get("relocation_required", "")),
                            "attribution_note": "Collected through JSearch/RapidAPI broad jobs API.",
                            "freshness_confidence": "source_posted_date" if item.get("job_posted_at_datetime_utc") or item.get("job_posted_at_timestamp") else "first_seen_only",
                        },
                        source,
                    )
                )
                # ponytail: cap API fanout here; add per-query quotas only if JSearch quality needs it.
                if limit > 0 and len(jobs) >= limit:
                    return jobs[:limit]
    return jobs


def collect_serpapi(source: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = env_secret("SERPAPI_KEY")
    if not api_key:
        raise RuntimeError("SerpApi credentials missing; set SERPAPI_KEY in backend/.env")
    jobs: list[dict[str, Any]] = []
    for term in search_terms(source):
        for location in source_locations(source):
            query = f"{term} {location}".strip()
            params = {"engine": "google_jobs", "q": query, "api_key": api_key, "hl": "en"}
            data = fetch_json(f"{source['url']}?{parse.urlencode(params)}")
            for item in data.get("jobs_results", []):
                apply_options = item.get("apply_options") or []
                apply_url = apply_options[0].get("link", "") if apply_options and isinstance(apply_options[0], dict) else item.get("share_link", "")
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("title", ""),
                            "company": item.get("company_name", ""),
                            "location": item.get("location", ""),
                            "source_url": item.get("share_link", "") or apply_url,
                            "apply_url": apply_url,
                            "description": plain_text(item.get("description", "")),
                            "freshness_confidence": "first_seen_only",
                            "external_id": item.get("job_id", ""),
                            "original_source": item.get("via", ""),
                            "attribution_note": "Collected through SerpApi Google Jobs; posted date is first-seen only unless source exposes one.",
                        },
                        source,
                    )
                )
    return jobs


def collect_remotive(source: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for term in search_terms(source):
        data = fetch_json(f"{source['url']}?{parse.urlencode({'search': term})}")
        for item in data.get("jobs", []):
            jobs.append(
                normalize_job(
                    {
                        "title": item.get("title", ""),
                        "company": item.get("company_name", ""),
                        "location": item.get("candidate_required_location") or "Remote",
                        "remote_status": "remote",
                        "source_url": item.get("url", ""),
                        "apply_url": item.get("url", ""),
                        "description": plain_text(item.get("description", "")),
                        "source_posted_at": item.get("publication_date", ""),
                        "external_id": item.get("id", ""),
                        "original_source": "Remotive",
                        "attribution_note": "Collected through Remotive public remote jobs API.",
                    },
                    source,
                )
            )
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


def filter_by_source_keywords(jobs: list[dict[str, Any]], source: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = [str(keyword).lower() for keyword in source.get("include_keywords", []) if str(keyword).strip()]
    if not keywords:
        return jobs
    fields = [str(field) for field in source.get("include_keyword_fields", ["title", "description", "requirements"])]
    return [
        job for job in jobs
        if any(keyword in " ".join(str(job.get(field, "")).lower() for field in fields) for keyword in keywords)
    ]


def apply_source_quality_controls(jobs: list[dict[str, Any]], source: dict[str, Any]) -> list[dict[str, Any]]:
    title_keywords = [str(item).lower() for item in source.get("title_keywords", []) if str(item).strip()]
    exclude_keywords = [
        str(item).lower()
        for item in [*(source.get("exclude_title_keywords") or []), *(source.get("exclude_seniority_keywords") or [])]
        if str(item).strip()
    ]

    def keep(job: dict[str, Any]) -> bool:
        title = str(job.get("title", "")).lower()
        if title_keywords and not any(keyword in title for keyword in title_keywords):
            return False
        if exclude_keywords and any(keyword in title for keyword in exclude_keywords):
            return False
        if source.get("include_remote") is False and "remote" in str(job.get("remote_status", "")).lower():
            return False
        return True

    filtered = [job for job in jobs if keep(job)]
    limit = int(source.get("max_jobs_per_source_per_refresh") or 0)
    return filtered[:limit] if limit > 0 else filtered


def finish_source_jobs(jobs: list[dict[str, Any]], source: dict[str, Any]) -> list[dict[str, Any]]:
    return apply_source_quality_controls(filter_by_source_keywords(jobs, source), source)


def collect_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    if not source.get("enabled", True):
        return []
    if source.get("coverage_tier") == "unsupported":
        return []
    if source.get("type") in EMAIL_ALERT_TYPES:
        return []
    if source["type"] == "manual":
        path = Path(source["url"])
        if not path.is_absolute():
            path = ROOT / path
        with open(path if path.exists() else SAMPLE_JOBS_PATH, "r", encoding="utf-8") as handle:
            return finish_source_jobs([normalize_job(item, source) for item in json.load(handle)], source)
    if source["type"] == "api" and source["name"].lower().startswith("usajobs"):
        return finish_source_jobs(collect_usajobs(source), source)
    if source["type"] == "api" and provider_name(source) == "adzuna":
        return finish_source_jobs(collect_adzuna(source), source)
    if source["type"] == "jsearch" or (source["type"] == "api" and provider_name(source) == "jsearch"):
        return finish_source_jobs(collect_jsearch(source), source)
    if source["type"] == "api" and provider_name(source) == "serpapi":
        return finish_source_jobs(collect_serpapi(source), source)
    if source["type"] == "api" and provider_name(source) == "remotive":
        return finish_source_jobs(collect_remotive(source), source)
    if source["type"] == "greenhouse":
        return finish_source_jobs(collect_greenhouse(source), source)
    if source["type"] == "lever":
        return finish_source_jobs(collect_lever(source), source)
    return []


def refresh_jobs(
    db_path: Path | str = db.DB_PATH,
    sources_override: list[dict[str, Any]] | None = None,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    load_backend_env()
    profile = load_profile()
    sources = sources_override or load_sources()
    db.init_db(db_path)
    for source in sources:
        db.upsert_source(source, db_path)

    new_jobs = duplicates = jobs_collected = jobs_scored = sources_checked = sources_skipped = marked_missing = 0
    email_alert_sources_checked = alert_emails_parsed = alert_jobs_inserted = alert_duplicates_updated = 0
    errors: dict[str, str] = {}
    source_results: list[dict[str, Any]] = []
    for source in sources:
        if not source.get("enabled", True):
            sources_skipped += 1
            db.mark_source_checked(source["name"], "disabled", db_path, jobs_found=0)
            continue
        sources_checked += 1
        if source.get("type") in EMAIL_ALERT_TYPES:
            email_alert_sources_checked += 1
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
            min_score = int(source.get("min_score_by_source") or 0)
            if min_score and int(scored.get("match_score") or 0) < min_score:
                continue
            if scored.get("is_closed_or_missing"):
                source_closed += 1
            job_id, duplicate = db.insert_job(scored, db_path)
            if duplicate:
                duplicates += 1
                source_duplicates += 1
                if source.get("type") in EMAIL_ALERT_TYPES:
                    alert_duplicates_updated += 1
                continue
            new_jobs += 1
            inserted += 1
            if source.get("type") in EMAIL_ALERT_TYPES:
                alert_jobs_inserted += 1
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

    from .email_alerts import ingest_gmail_alerts

    gmail_result = ingest_gmail_alerts(db_path)
    if gmail_result["gmail_configured"]:
        gmail_source_names = [source["name"] for source in sources if source.get("coverage_tier") == "big_board_email_alert"]
        email_alert_sources_checked += len(gmail_source_names)
        alert_emails_parsed += int(gmail_result["alert_emails_parsed"])
        alert_jobs_inserted += int(gmail_result["alert_jobs_inserted"])
        alert_duplicates_updated += int(gmail_result["alert_duplicates_updated"])
        new_jobs += alert_jobs_inserted
        duplicates += alert_duplicates_updated
        jobs_collected += alert_jobs_inserted + alert_duplicates_updated
        jobs_scored += alert_jobs_inserted + alert_duplicates_updated
        status = f"ok: {alert_jobs_inserted} new, {alert_duplicates_updated} duplicates"
        error = "; ".join(gmail_result.get("gmail_errors", []))
        for name in gmail_source_names:
            db.mark_source_checked(name, status if not error else f"error: {error}", db_path, jobs_found=alert_jobs_inserted + alert_duplicates_updated, error=error)

    include_sample = api_env() == "local"
    counts = db.freshness_counts(db_path, include_sample=include_sample)
    active_jobs = db.list_jobs(path=db_path, active_only=True, include_sample=include_sample)
    bands = {
        "high_matches": sum(1 for item in active_jobs if item["match_score"] >= 70),
        "medium_matches": sum(1 for item in active_jobs if 55 <= item["match_score"] < 70),
        "low_matches": sum(1 for item in active_jobs if item["match_score"] < 55),
    }
    result = {
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
        "email_alert_sources_checked": email_alert_sources_checked,
        "alert_emails_checked": int(gmail_result.get("alert_emails_checked", 0)),
        "alert_emails_parsed": alert_emails_parsed,
        "alert_jobs_inserted": alert_jobs_inserted,
        "alert_duplicates_updated": alert_duplicates_updated,
        "alert_parse_errors": int(gmail_result.get("alert_parse_errors", 0)),
        "gmail_errors": gmail_result.get("gmail_errors", []),
        "gmail_configured": bool(gmail_result.get("gmail_configured")),
        **db.review_counts(db_path, include_sample=include_sample),
        **counts,
        **bands,
    }
    report_path = write_daily_report(result, active_jobs, report_dir) if report_dir else write_daily_report(result, active_jobs)
    db.save_daily_report(
        report_path.stem.removeprefix("daily_review_"),
        db.now_iso(),
        "refresh_jobs",
        summary_counts(result),
        report_path.read_text(encoding="utf-8"),
        db_path,
    )
    result["daily_report_path"] = str(report_path)
    return result
