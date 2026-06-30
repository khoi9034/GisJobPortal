from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .collectors import normalize_job, plain_text

LINK_RE = re.compile(r"https?://[^\s<>\")]+", re.I)
JOB_ID_RE = re.compile(r"(?:currentJobId|jk|jobId|job_id|jobs/view|view/)(?:=|/)([A-Za-z0-9_-]+)", re.I)


def extract_job_links(text: str) -> list[str]:
    links: list[str] = []
    for raw in LINK_RE.findall(text or ""):
        link = raw.rstrip(".,;]")
        parts = urlsplit(link)
        if parts.netloc.endswith("linkedin.com") or "indeed." in parts.netloc:
            qs = parse_qs(parts.query)
            link = unquote((qs.get("url") or qs.get("u") or [link])[0])
            links.append(link)
    return list(dict.fromkeys(links))


def _source_from_hint(source_hint: str) -> dict[str, str]:
    is_indeed = source_hint.lower().startswith("indeed")
    return {
        "name": "Indeed Job Alerts Email" if is_indeed else "LinkedIn Job Alerts Email",
        "type": "indeed_email_alert" if is_indeed else "linkedin_email_alert",
        "url": "gmail://job-alerts/indeed" if is_indeed else "gmail://job-alerts/linkedin",
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
                "description": f"{snippet}\n\nDescription missing — open job link to review.",
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


def normalize_alert_email(source_hint: str, raw_email_text: str, message_id: str = "") -> list[dict[str, Any]]:
    provider = "indeed" if source_hint.lower().startswith("indeed") else "linkedin"
    rows = parse_indeed_alert_text(raw_email_text) if provider == "indeed" else parse_linkedin_alert_text(raw_email_text)
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
