from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
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
from .materials import generate_materials
from .paths import api_env, cors_origins
from .profile import load_profile
from .reports import latest_report as latest_daily_report
from .scoring import score_job
from .source_validation import validate_sources
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


def ensure_seeded() -> None:
    db.init_db()
    if not db.list_jobs():
        refresh_jobs()


@app.get("/health")
def health() -> dict[str, str]:
    with db.connection() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "api_env": api_env(), "database": "connected"}


@app.get("/jobs")
def jobs(status: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
    ensure_seeded()
    return db.list_jobs(status=status, active_only=active_only)


@app.get("/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    ensure_seeded()
    found = db.get_job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Job not found")
    return found


@app.post("/jobs/refresh")
def refresh() -> dict[str, Any]:
    return refresh_jobs()


@app.get("/review/queue")
def review_queue(include_stale: bool = False) -> dict[str, list[dict[str, Any]]]:
    ensure_seeded()
    return db.review_queue(include_stale=include_stale)


@app.get("/application/board")
def application_board() -> dict[str, list[dict[str, Any]]]:
    ensure_seeded()
    return db.application_board()


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
def overview() -> dict[str, Any]:
    ensure_seeded()
    jobs = db.list_jobs()
    return {
        "total": len(jobs),
        "high_matches": sum(1 for item in jobs if item["match_score"] >= 70),
        "medium_matches": sum(1 for item in jobs if 55 <= item["match_score"] < 70),
        "low_matches": sum(1 for item in jobs if item["match_score"] < 55),
        "by_status": {status: sum(1 for item in jobs if item["status"] == status) for status in sorted(db.VALID_STATUSES)},
    }


@app.get("/sources")
def sources() -> list[dict[str, Any]]:
    configured = load_sources()
    for source in configured:
        db.upsert_source(source)
    saved = {source["name"]: source for source in db.list_sources()}
    return [saved.get(source["name"], source) for source in configured]


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
