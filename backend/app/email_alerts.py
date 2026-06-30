from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from urllib.parse import parse_qs, unquote, urlsplit

from . import db
from .collectors import normalize_job, plain_text
from .paths import ROOT, load_backend_env
from .profile import load_profile
from .scoring import score_job

LINK_RE = re.compile(r"https?://[^\s<>\")]+", re.I)
JOB_ID_RE = re.compile(r"(?:currentJobId|jk|jobId|job_id|jobs/view|view/)(?:=|/)([A-Za-z0-9_-]+)", re.I)
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DEFAULT_ALERT_QUERY = '(from:linkedin.com OR from:indeed.com OR subject:("job alert") OR subject:(GIS) OR subject:(geospatial)) newer_than:14d'

ALERT_PROVIDERS = {
    "linkedin": ("LinkedIn Job Alerts Email", "linkedin_email_alert", "gmail://job-alerts/linkedin"),
    "indeed": ("Indeed Job Alerts Email", "indeed_email_alert", "gmail://job-alerts/indeed"),
    "jobstreet": ("JobStreet JobsDB Job Alerts Email", "gmail_job_alerts", "gmail://job-alerts/jobstreet-jobsdb"),
    "jobsdb": ("JobStreet JobsDB Job Alerts Email", "gmail_job_alerts", "gmail://job-alerts/jobstreet-jobsdb"),
    "glints": ("Glints Job Alerts Email", "gmail_job_alerts", "gmail://job-alerts/glints"),
    "vietnamworks": ("VietnamWorks Job Alerts Email", "gmail_job_alerts", "gmail://job-alerts/vietnamworks"),
    "topcv": ("TopCV Job Alerts Email", "gmail_job_alerts", "gmail://job-alerts/topcv"),
}

ALERT_QUERY_PROFILES = {
    "linkedin_indeed_us": '(from:linkedin.com OR from:indeed.com) (GIS OR geospatial OR "spatial analyst") newer_than:14d',
    "linkedin_indeed_sea": '(from:linkedin.com OR from:indeed.com) (Vietnam OR Singapore OR Malaysia OR Thailand OR Indonesia OR Philippines OR APAC) (GIS OR geospatial) newer_than:14d',
    "jobstreet_jobsdb": '(from:jobstreet.com OR from:jobsdb.com OR subject:(JobStreet) OR subject:(JobsDB)) (GIS OR geospatial OR "urban planning") newer_than:14d',
    "glints": '(from:glints.com OR subject:(Glints)) (GIS OR geospatial OR "data analyst" OR planning) newer_than:14d',
    "vietnamworks_topcv": '(from:vietnamworks.com OR from:topcv.vn OR subject:(VietnamWorks) OR subject:(TopCV)) (GIS OR QGIS OR ArcGIS OR "urban planning") newer_than:14d',
}


def extract_job_links(text: str) -> list[str]:
    links: list[str] = []
    for raw in LINK_RE.findall(text or ""):
        link = raw.rstrip(".,;]")
        parts = urlsplit(link)
        if provider_from_text(parts.netloc) or any(key in parse_qs(parts.query) for key in ("url", "u")):
            qs = parse_qs(parts.query)
            links.append(unquote((qs.get("url") or qs.get("u") or [link])[0]))
    return list(dict.fromkeys(links))


def provider_from_text(text: str) -> str:
    lowered = text.lower()
    return next((provider for provider in ALERT_PROVIDERS if provider in lowered), "")


def _source_from_hint(source_hint: str) -> dict[str, str]:
    provider = provider_from_text(source_hint) or "linkedin"
    name, source_type, url = ALERT_PROVIDERS[provider]
    return {
        "name": name,
        "type": source_type,
        "url": url,
    }


def _parse_blocks(text: str, provider: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lines = [plain_text(line) for line in re.split(r"\r?\n", text or "") if plain_text(line)]
    links = extract_job_links(text)
    for index, line in enumerate(lines):
        match = re.match(r"^(?P<title>[^|–—@]+?)\s*(?:at|@|\||–|—|-)\s*(?P<company>[^|–—,]+)(?:[,|–—-]\s*(?P<location>.+))?$", line, re.I)
        if not match:
            continue
        url = links[min(len(rows), len(links) - 1)] if links else ""
        title = match.group("title").strip()
        company = match.group("company").strip()
        location = (match.group("location") or "").strip() or "Unknown"
        snippet = " ".join(lines[index : index + 3])
        rows.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "source_url": url,
                "apply_url": url,
                "description": f"{snippet}\n\nDescription missing - open job link to review.",
                "requirements": snippet,
                "external_id": extract_alert_job_id(url) or f"{provider}:{title}:{company}:{location}",
                "original_source": provider.title(),
                "attribution_note": f"Imported from {provider.title()} job alert email; no site scraping or login automation.",
                "freshness_confidence": "first_seen_only",
            }
        )
    return rows


def extract_alert_job_id(url: str) -> str:
    match = JOB_ID_RE.search(url or "")
    return match.group(1) if match else ""


def parse_linkedin_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "linkedin")


def parse_indeed_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "indeed")


def parse_jobstreet_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "jobstreet")


def parse_glints_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "glints")


def parse_vietnamworks_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "vietnamworks")


def parse_topcv_alert_text(text: str) -> list[dict[str, Any]]:
    return _parse_blocks(text, "topcv")


def normalize_alert_email(source_hint: str, raw_email_text: str, message_id: str = "") -> list[dict[str, Any]]:
    provider = provider_from_text(source_hint) or "linkedin"
    parser = {
        "indeed": parse_indeed_alert_text,
        "jobstreet": parse_jobstreet_alert_text,
        "jobsdb": parse_jobstreet_alert_text,
        "glints": parse_glints_alert_text,
        "vietnamworks": parse_vietnamworks_alert_text,
        "topcv": parse_topcv_alert_text,
    }.get(provider, parse_linkedin_alert_text)
    rows = parser(raw_email_text)
    if message_id:
        for row in rows:
            row["external_id"] = row.get("external_id") or message_id
    return rows


def create_job_from_alert(alert: dict[str, Any], source_hint: str) -> dict[str, Any]:
    return normalize_job(alert, _source_from_hint(source_hint))


def dedupe_alert_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        key = (
            str(job.get("apply_url") or job.get("source_url") or "").lower(),
            str(job.get("title", "")).strip().lower(),
            str(job.get("company", "")).strip().lower(),
            str(job.get("location", "")).strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def parse_alert_jobs(source_hint: str, raw_email_text: str, message_id: str = "") -> list[dict[str, Any]]:
    alerts = normalize_alert_email(source_hint, raw_email_text, message_id)
    return dedupe_alert_jobs([create_job_from_alert(alert, source_hint) for alert in alerts])


def gmail_config() -> dict[str, str]:
    load_backend_env()
    return {
        "enabled": os.getenv("GMAIL_INGESTION_ENABLED", "false").lower(),
        "client_id": os.getenv("GMAIL_CLIENT_ID", ""),
        "client_secret": os.getenv("GMAIL_CLIENT_SECRET", ""),
        "token_path": os.getenv("GMAIL_TOKEN_PATH", "runtime/secrets/gmail_token.local.json"),
        "token_json_base64": os.getenv("GMAIL_TOKEN_JSON_BASE64", ""),
        "query": os.getenv("GMAIL_ALERT_QUERY", DEFAULT_ALERT_QUERY),
    }


def gmail_alert_query_profiles() -> dict[str, str]:
    return ALERT_QUERY_PROFILES.copy()


def _usable_secret(value: str) -> bool:
    return bool(value and not value.lower().startswith("replace_"))


def load_gmail_token(config: dict[str, str] | None = None) -> dict[str, Any]:
    config = config or gmail_config()
    if _usable_secret(config.get("token_json_base64", "")):
        try:
            return json.loads(base64.b64decode(config["token_json_base64"]).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}
    path = ROOT / config.get("token_path", "runtime/secrets/gmail_token.local.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def gmail_configured(config: dict[str, str] | None = None) -> bool:
    config = config or gmail_config()
    return (
        config["enabled"] == "true"
        and _usable_secret(config["client_id"])
        and _usable_secret(config["client_secret"])
        and bool(load_gmail_token(config))
    )


def refresh_gmail_token(config: dict[str, str], token: dict[str, Any]) -> dict[str, Any]:
    refresh_token = token.get("refresh_token", "")
    if not refresh_token:
        return token
    payload = parse.urlencode(
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = request.Request("https://oauth2.googleapis.com/token", data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    token.update(data)
    if data.get("expires_in"):
        token["expires_at"] = int(time.time()) + int(data["expires_in"])
    return token


def gmail_access_token(config: dict[str, str], token: dict[str, Any]) -> str:
    if token.get("access_token") and int(token.get("expires_at") or 0) > int(time.time()) + 60:
        return str(token["access_token"])
    return str(refresh_gmail_token(config, token).get("access_token", ""))


def gmail_get(path: str, params: dict[str, str] | None = None, config: dict[str, str] | None = None, token: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or gmail_config()
    token = token or load_gmail_token(config)
    access_token = gmail_access_token(config, token)
    if not access_token:
        raise RuntimeError("Gmail access token missing; run scripts/setup_gmail_oauth.py")
    url = f"{GMAIL_API}{path}"
    if params:
        url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code == 401 and token.get("refresh_token"):
            access_token = gmail_access_token(config, refresh_gmail_token(config, token))
            req = request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            with request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        raise


def gmail_search_messages(config: dict[str, str] | None = None, max_results: int = 25) -> list[dict[str, Any]]:
    config = config or gmail_config()
    data = gmail_get("/messages", {"q": config["query"], "maxResults": str(max_results)}, config=config)
    return data.get("messages", [])


def gmail_message_text(message: dict[str, Any]) -> str:
    chunks: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data", "")
        if data and mime in {"text/plain", "text/html"}:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="ignore")
            chunks.append(plain_text(raw))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(message.get("payload") or {})
    return "\n".join(chunk for chunk in chunks if chunk)


def source_hint_from_message(message: dict[str, Any], text: str) -> str:
    headers = {header.get("name", "").lower(): header.get("value", "") for header in (message.get("payload") or {}).get("headers", [])}
    combined = f"{headers.get('from', '')} {headers.get('subject', '')} {text}".lower()
    return provider_from_text(combined) or "linkedin"


def gmail_fetch_alert_texts(config: dict[str, str] | None = None, max_results: int = 25) -> list[dict[str, str]]:
    config = config or gmail_config()
    rows: list[dict[str, str]] = []
    for row in gmail_search_messages(config, max_results=max_results):
        message = gmail_get(f"/messages/{row['id']}", {"format": "full"}, config=config)
        text = gmail_message_text(message)
        rows.append({"id": row["id"], "source_hint": source_hint_from_message(message, text), "text": text})
    return rows


def ingest_gmail_alerts(db_path: Path | str = db.DB_PATH, max_results: int = 25) -> dict[str, Any]:
    config = gmail_config()
    result = {
        "gmail_configured": gmail_configured(config),
        "alert_emails_checked": 0,
        "alert_emails_parsed": 0,
        "alert_jobs_inserted": 0,
        "alert_duplicates_updated": 0,
        "alert_parse_errors": 0,
        "gmail_errors": [],
    }
    if not result["gmail_configured"]:
        return result
    profile = load_profile()
    try:
        emails = gmail_fetch_alert_texts(config, max_results=max_results)
    except Exception as exc:
        result["gmail_errors"].append(str(exc))
        return result
    result["alert_emails_checked"] = len(emails)
    for item in emails:
        try:
            jobs = parse_alert_jobs(item["source_hint"], item["text"], item["id"])
        except Exception:
            result["alert_parse_errors"] += 1
            continue
        result["alert_emails_parsed"] += int(bool(jobs))
        for job in jobs:
            scored = {**job, **score_job(job, profile)}
            _, duplicate = db.insert_job(scored, db_path)
            result["alert_duplicates_updated"] += int(duplicate)
            result["alert_jobs_inserted"] += int(not duplicate)
    return result
