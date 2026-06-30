from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db
from .collectors import collect_from_source
from .paths import GENERATED_DIR, PRIVATE_DIR, ROOT, load_backend_env
from .sources import load_sources

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")
PROVIDER_ENV = {
    "adzuna": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
    "jsearch": ("RAPIDAPI_KEY",),
    "serpapi": ("SERPAPI_KEY",),
}


def redact(value: str) -> str:
    text = str(value)
    for path in (PRIVATE_DIR, GENERATED_DIR, ROOT):
        text = text.replace(str(path), "[local-path]")
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            text = text.replace(secret, "[redacted]")
    return text


def support(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "supports_posted_date": bool(source.get("posted_date_supported")),
        "supports_updated_date": bool(source.get("updated_date_supported")),
        "supports_close_date": bool(source.get("close_date_supported")),
        "first_seen_only": bool(source.get("first_seen_only", True)),
        "freshness_confidence_default": "first_seen_only" if source.get("first_seen_only", True) else "source_posted_date",
    }


def config_error(source: dict[str, Any]) -> str:
    kind = source.get("type")
    if not source.get("name") or not kind:
        return "Source requires name and type"
    if kind == "greenhouse" and not (source.get("board_token") or source.get("url")):
        return "Greenhouse source requires board_token or URL"
    if kind == "lever" and not (source.get("site") or source.get("url")):
        return "Lever source requires site or URL"
    if kind in {"manual", "api", "rss", "static_url"} and not source.get("url"):
        return f"{kind} source requires url"
    return ""


def missing_required_credentials(source: dict[str, Any]) -> list[str]:
    provider = str(source.get("provider", "")).lower()
    if source.get("name", "").lower().startswith("usajobs"):
        required = ("USAJOBS_USER_AGENT", "USAJOBS_AUTHORIZATION_KEY")
    else:
        required = source.get("required_env") or PROVIDER_ENV.get(provider, ())
    if not required:
        return []
    if not any(str(name) in os.environ for name in required):
        load_backend_env()
    missing = []
    for name in required:
        if name == "USAJOBS_AUTHORIZATION_KEY":
            value = (os.getenv("USAJOBS_AUTHORIZATION_KEY") or os.getenv("USAJOBS_API_KEY") or "").strip()
        else:
            value = os.getenv(str(name), "").strip()
        if not value or value.lower().startswith("replace_"):
            missing.append(str(name))
    return missing


def validate_source(source: dict[str, Any], sample_size: int = 3) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    base = {
        "name": source.get("name", ""),
        "type": source.get("type", ""),
        "url": source.get("url", ""),
        "enabled": bool(source.get("enabled", True)),
        "notes": source.get("notes", ""),
        "coverage_tier": source.get("coverage_tier", ""),
        "requires_api_key": bool(source.get("requires_api_key")),
        "credentials_configured": not missing_required_credentials(source),
        "terms_notes": source.get("terms_notes", ""),
        "quality_score": source.get("quality_score"),
        "dedupe_priority": source.get("dedupe_priority"),
        "valid_config": True,
        "reachable_endpoint": False,
        "jobs_returned": False,
        "jobs_sampled": 0,
        "jobs_found_last_run": 0,
        "last_validated_at": now,
        "last_error": "",
        **support(source),
    }
    error = config_error(source)
    if error:
        return {**base, "valid_config": False, "status": "error", "validation_status": "error", "last_error": error}
    if not source.get("enabled", True):
        return {**base, "status": "disabled", "validation_status": "disabled"}
    missing = missing_required_credentials(source)
    if missing:
        return {
            **base,
            "credentials_configured": False,
            "status": "warning",
            "validation_status": "warning",
            "last_error": f"Credentials missing: {', '.join(missing)}",
        }
    try:
        jobs = collect_from_source(source)
        sample = jobs[:sample_size]
        return {
            **base,
            "status": "ok" if jobs else "warning",
            "validation_status": "ok" if jobs else "warning",
            "reachable_endpoint": True,
            "jobs_returned": bool(jobs),
            "jobs_sampled": len(sample),
            "jobs_found_last_run": len(jobs),
            "last_error": "" if jobs else "No jobs returned",
            "sample_titles": [job.get("title", "") for job in sample],
        }
    except Exception as exc:
        message = redact(str(exc))
        status = "warning" if "credentials missing" in message.lower() else "error"
        return {**base, "status": status, "validation_status": status, "last_error": message}


def validate_sources(
    sources: list[dict[str, Any]] | None = None,
    db_path: Path | str = db.DB_PATH,
    store: bool = False,
) -> list[dict[str, Any]]:
    configured = sources or load_sources()
    rows = [validate_source(source) for source in configured]
    if store:
        for source, summary in zip(configured, rows):
            db.record_source_validation(source, summary, db_path)
    return rows
