from __future__ import annotations

import os
import subprocess
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .ai.service import ai_status
from .collectors import refresh_jobs
from .documents import (
    extract_resume,
    extract_transcript,
    generate_application_packet,
    get_application_packet,
    resume_summary,
    transcript_summary,
)
from .email_alerts import gmail_configured, parse_alert_jobs
from .materials import generate_materials
from .paths import ROOT, admin_refresh_token, api_env, cors_origins, database_runtime_type, database_type, database_url_present, database_url_scheme, load_backend_env
from .profile import load_profile
from .reports import latest_report as latest_daily_report
from .reports import redact
from .scoring import score_job
from .source_validation import missing_required_credentials, validate_sources
from .sources import load_sources, save_source

app = FastAPI(title="GIS Apply Copilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StatusPatch(BaseModel):
    status: str


class NotesPatch(BaseModel):
    notes: str


class ReviewPatch(BaseModel):
    review_status: str | None = None
    review_notes: str | None = None
    priority_bucket: str | None = None


class ApplicationPatch(BaseModel):
    application_url_opened_at: str | None = None
    application_started_at: str | None = None
    applied_at: str | None = None
    follow_up_due_at: str | None = None
    follow_up_sent_at: str | None = None
    application_method: str | None = None
    application_contact_name: str | None = None
    application_contact_email: str | None = None
    application_confirmation_number: str | None = None
    application_submission_notes: str | None = None
    outcome_status: str | None = None


class ChecklistPatch(BaseModel):
    checklist: dict[str, Any] | None = None
    resume_required: bool | None = None
    cover_letter_required: bool | None = None
    transcript_required: bool | None = None
    portfolio_link_included: bool | None = None
    references_required: bool | None = None
    writing_sample_required: bool | None = None
    other_documents: str | None = None


class SourceIn(BaseModel):
    name: str
    type: str
    url: str
    enabled: bool = True
    notes: str = ""
    board_token: str | None = None
    site: str | None = None
    company: str | None = None
    posted_date_supported: bool = False
    close_date_supported: bool = False
    updated_date_supported: bool = False
    first_seen_only: bool = True
    freshness_confidence_default: str | None = None


class AlertEmailImport(BaseModel):
    source_hint: str
    raw_email_text: str


def ensure_seeded() -> None:
    db.init_db()
    if not db.list_jobs():
        refresh_jobs()


def should_include_sample(include_sample: bool = False) -> bool:
    return include_sample or api_env() == "local"


def require_admin_refresh_token(x_admin_refresh_token: str | None = None) -> None:
    expected = admin_refresh_token()
    if api_env() != "production":
        if expected and x_admin_refresh_token and x_admin_refresh_token != expected:
            raise HTTPException(status_code=403, detail="Invalid admin refresh token")
        return
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_REFRESH_TOKEN is not configured")
    if x_admin_refresh_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin refresh token")


def refresh_summary(result: dict[str, Any]) -> dict[str, Any]:
    errors = {redact(source): redact(message) for source, message in (result.get("errors") or {}).items()}
    return {
        "sources_checked": result.get("sources_checked", 0),
        "jobs_collected": result.get("jobs_collected", 0),
        "inserted": result.get("new_jobs_inserted", 0),
        "new_jobs_found": result.get("new_jobs_found", 0),
        "duplicates_skipped": result.get("duplicates_skipped", 0),
        "duplicates_updated": result.get("duplicates_updated", 0),
        "stale_jobs": result.get("stale_jobs", 0),
        "strong_excellent_matches": result.get("high_matches", 0),
        "source_errors": errors,
        "report_generated": bool(result.get("daily_report_path")),
        "email_alert_sources_checked": result.get("email_alert_sources_checked", 0),
        "alert_emails_checked": result.get("alert_emails_checked", 0),
        "alert_emails_parsed": result.get("alert_emails_parsed", 0),
        "alert_jobs_inserted": result.get("alert_jobs_inserted", 0),
        "alert_duplicates_updated": result.get("alert_duplicates_updated", 0),
        "alert_parse_errors": result.get("alert_parse_errors", 0),
        "gmail_errors": [redact(message) for message in result.get("gmail_errors", [])],
        "gmail_configured": result.get("gmail_configured", False),
    }


@app.get("/health")
def health() -> dict[str, str]:
    with db.connection() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "api_env": api_env(), "database": "connected", "version": app_version()}


def app_version() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@app.get("/deployment/status")
def deployment_status() -> dict[str, Any]:
    configured_sources = load_sources()
    jobs = db.list_jobs(include_sample=should_include_sample())
    sample_jobs = db.list_jobs(include_sample=True)
    runtime_type = database_runtime_type()
    real_sources_enabled = sum(1 for source in configured_sources if source.get("enabled") and source.get("name") != "Sample GIS Jobs")
    blockers = []
    if api_env() != "production":
        blockers.append("API_ENV is not production")
    if not database_url_present():
        blockers.append("DATABASE_URL is missing")
    if runtime_type != "postgres":
        blockers.append("database runtime is not postgres")
    if real_sources_enabled <= 0:
        blockers.append("no real sources enabled")
    return {
        "api_env": api_env(),
        "database_type": runtime_type,
        "database_runtime_type": runtime_type,
        "configured_database_type": database_type(),
        "database_url_present": database_url_present(),
        "database_url_scheme": database_url_scheme(),
        "database": "connected",
        "cors_origins_count": len(cors_origins()),
        "source_count": len(configured_sources),
        "job_count": len(jobs),
        "sample_job_count": sum(1 for job in sample_jobs if job.get("source") == db.SAMPLE_JOB_SOURCE),
        "real_sources_enabled": real_sources_enabled,
        "production_blockers": blockers,
        "production_ready": not blockers,
        "version": app_version(),
    }


@app.get("/jobs")
def jobs(status: str | None = None, active_only: bool = False, include_sample: bool = False) -> list[dict[str, Any]]:
    ensure_seeded()
    return db.list_jobs(status=status, active_only=active_only, include_sample=should_include_sample(include_sample))


@app.get("/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    ensure_seeded()
    found = db.get_job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Job not found")
    return found


@app.post("/jobs/refresh")
def refresh(x_admin_refresh_token: str | None = Header(default=None, alias="X-Admin-Refresh-Token")) -> dict[str, Any]:
    require_admin_refresh_token(x_admin_refresh_token)
    return refresh_summary(refresh_jobs())


@app.post("/imports/job-alert-email-text")
def import_job_alert_email_text(payload: AlertEmailImport, x_admin_refresh_token: str | None = Header(default=None, alias="X-Admin-Refresh-Token")) -> dict[str, Any]:
    require_admin_refresh_token(x_admin_refresh_token)
    source_hint = payload.source_hint.lower().strip()
    if source_hint not in {"linkedin", "indeed"}:
        raise HTTPException(status_code=400, detail="source_hint must be linkedin or indeed")
    profile = load_profile()
    inserted = duplicates = 0
    jobs: list[dict[str, Any]] = []
    for job in parse_alert_jobs(source_hint, payload.raw_email_text):
        scored = {**job, **score_job(job, profile)}
        job_id, duplicate = db.insert_job(scored)
        duplicates += int(duplicate)
        inserted += int(not duplicate)
        stored = db.get_job(job_id) if job_id else None
        if stored:
            jobs.append(stored)
    return {"source": "LinkedIn Job Alerts Email" if source_hint == "linkedin" else "Indeed Job Alerts Email", "inserted": inserted, "duplicates_updated": duplicates, "jobs": jobs}


@app.post("/admin/refresh-jobs")
def admin_refresh_jobs(x_admin_refresh_token: str | None = Header(default=None, alias="X-Admin-Refresh-Token")) -> dict[str, Any]:
    require_admin_refresh_token(x_admin_refresh_token)
    return refresh_summary(refresh_jobs())


@app.get("/review/queue")
def review_queue(include_stale: bool = False, include_sample: bool = False) -> dict[str, list[dict[str, Any]]]:
    ensure_seeded()
    return db.review_queue(include_stale=include_stale, include_sample=should_include_sample(include_sample))


@app.get("/review/apply-today")
def apply_today(limit: int = 5, include_stale: bool = False, include_sample: bool = False) -> list[dict[str, Any]]:
    ensure_seeded()
    return db.apply_today(limit=limit, include_stale=include_stale, include_sample=should_include_sample(include_sample))


@app.get("/application/board")
def application_board(include_sample: bool = False) -> dict[str, list[dict[str, Any]]]:
    ensure_seeded()
    return db.application_board(include_sample=should_include_sample(include_sample))


@app.get("/reports/latest")
def latest_report() -> dict[str, Any]:
    return latest_daily_report()


@app.post("/jobs/{job_id}/score")
def score(job_id: int) -> dict[str, Any]:
    found = db.get_job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Job not found")
    scored = score_job(found, load_profile())
    return db.update_job_fields(job_id, scored)


@app.post("/jobs/{job_id}/generate-materials")
def materials(job_id: int) -> dict[str, Any]:
    found = db.get_job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Job not found")
    generated = generate_materials(found, load_profile())
    return db.save_materials(job_id, generated)


@app.post("/jobs/{job_id}/generate-application-packet")
def application_packet_generate(job_id: int) -> dict[str, Any]:
    try:
        return generate_application_packet(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/ai/status")
def ai_status_endpoint() -> dict[str, object]:
    return ai_status()


@app.get("/jobs/{job_id}/application-packet")
def application_packet(job_id: int) -> dict[str, Any]:
    try:
        return get_application_packet(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/jobs/{job_id}/status")
def status(job_id: int, patch: StatusPatch) -> dict[str, Any]:
    try:
        return db.update_job_fields(job_id, {"status": patch.status})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/jobs/{job_id}/notes")
def notes(job_id: int, patch: NotesPatch) -> dict[str, Any]:
    try:
        return db.update_job_fields(job_id, {"notes": patch.notes})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/jobs/{job_id}/review")
def review(job_id: int, patch: ReviewPatch) -> dict[str, Any]:
    try:
        return db.update_job_review(job_id, patch.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/jobs/{job_id}/application")
def application(job_id: int, patch: ApplicationPatch) -> dict[str, Any]:
    try:
        return db.update_job_application(job_id, patch.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/jobs/{job_id}/mark-application-started")
def mark_application_started(job_id: int) -> dict[str, Any]:
    try:
        return db.mark_application_started(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/jobs/{job_id}/mark-applied")
def mark_applied(job_id: int) -> dict[str, Any]:
    try:
        return db.mark_applied(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/jobs/{job_id}/mark-follow-up-sent")
def mark_follow_up_sent(job_id: int) -> dict[str, Any]:
    try:
        return db.mark_follow_up_sent(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/jobs/{job_id}/document-checklist")
def document_checklist(job_id: int, patch: ChecklistPatch) -> dict[str, Any]:
    data = patch.model_dump(exclude_none=True)
    updates = data.pop("checklist", None) or data
    try:
        found = db.get_job(job_id)
        if not found:
            raise LookupError(f"Job {job_id} not found")
        checklist = {**(found.get("document_checklist") or {}), **updates}
        return db.update_job_fields(job_id, {"document_checklist": checklist})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/documents/resume/extract")
def resume_extract() -> dict[str, Any]:
    try:
        return extract_resume()
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/documents/resume/summary")
def resume_get_summary() -> dict[str, Any]:
    return resume_summary()


@app.post("/documents/transcript/extract")
def transcript_extract() -> dict[str, Any]:
    try:
        return extract_transcript()
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/documents/transcript/summary")
def transcript_get_summary() -> dict[str, Any]:
    return transcript_summary()


@app.get("/stats/overview")
def overview(include_sample: bool = False) -> dict[str, Any]:
    ensure_seeded()
    jobs = db.list_jobs(include_sample=should_include_sample(include_sample))
    return {
        "total": len(jobs),
        "high_matches": sum(1 for item in jobs if item["match_score"] >= 70),
        "medium_matches": sum(1 for item in jobs if 55 <= item["match_score"] < 70),
        "low_matches": sum(1 for item in jobs if item["match_score"] < 55),
        "by_status": {status: sum(1 for item in jobs if item["status"] == status) for status in sorted(db.VALID_STATUSES)},
    }


@app.get("/sources")
def sources() -> list[dict[str, Any]]:
    load_backend_env()
    gmail_is_configured = gmail_configured()
    gmail_enabled = os.getenv("GMAIL_INGESTION_ENABLED", "false").lower() == "true"
    configured = load_sources()
    try:
        saved = {source["name"]: source for source in db.list_sources()}
    except Exception:
        saved = {}
    try:
        live_jobs = db.list_jobs(include_sample=should_include_sample())
    except Exception:
        live_jobs = []
    source_counts: dict[str, dict[str, int]] = {}
    for item in live_jobs:
        bucket = source_counts.setdefault(item.get("source", ""), {"jobs_total": 0, "strong_matches": 0})
        bucket["jobs_total"] += 1
        bucket["strong_matches"] += int(int(item.get("match_score") or 0) >= 70)
    rows = []
    for source in configured:
        row = {**source, **saved.get(source["name"], {})}
        missing = missing_required_credentials(source)
        row.setdefault("supports_posted_date", bool(row.get("posted_date_supported", False)))
        row.setdefault("supports_updated_date", bool(row.get("updated_date_supported", False)))
        row.setdefault("supports_close_date", bool(row.get("close_date_supported", False)))
        row.setdefault("freshness_confidence_default", "first_seen_only" if row.get("first_seen_only", True) else "source_posted_date")
        row.setdefault("last_checked_at", row.get("last_checked", ""))
        row.setdefault("last_error", row.get("errors_last_run", ""))
        row.setdefault("validation_status", "disabled" if not row.get("enabled") else row.get("status", "unknown"))
        row["credentials_configured"] = not missing
        row["credential_missing"] = bool(missing)
        row["gmail_configured"] = gmail_is_configured if row.get("coverage_tier") == "big_board_email_alert" else None
        row["gmail_ingestion_enabled"] = gmail_enabled if row.get("coverage_tier") == "big_board_email_alert" else None
        row["gmail_alert_query"] = os.getenv("GMAIL_ALERT_QUERY", "(from:linkedin.com OR from:indeed.com) newer_than:14d") if row.get("coverage_tier") == "big_board_email_alert" else ""
        row.update(source_counts.get(source["name"], {"jobs_total": 0, "strong_matches": 0}))
        rows.append(row)
    return rows


@app.get("/sources/validate")
def validate_source_config() -> list[dict[str, Any]]:
    return validate_sources(store=True)


@app.get("/profile")
def profile() -> dict[str, Any]:
    return load_profile()


@app.post("/sources")
def add_source(source: SourceIn) -> dict[str, Any]:
    try:
        saved = save_source(source.model_dump(exclude_none=True))
        db.upsert_source(saved)
        return saved
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
