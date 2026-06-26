from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .collectors import refresh_jobs
from .materials import generate_materials
from .profile import load_profile
from .scoring import score_job
from .sources import load_sources, save_source

app = FastAPI(title="GIS Apply Copilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StatusPatch(BaseModel):
    status: str


class NotesPatch(BaseModel):
    notes: str


class SourceIn(BaseModel):
    name: str
    type: str
    url: str
    enabled: bool = True
    notes: str = ""


def ensure_seeded() -> None:
    db.init_db()
    if not db.list_jobs():
        refresh_jobs()


@app.get("/jobs")
def jobs(status: str | None = None) -> list[dict[str, Any]]:
    ensure_seeded()
    return db.list_jobs(status=status)


@app.get("/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    ensure_seeded()
    found = db.get_job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Job not found")
    return found


@app.post("/jobs/refresh")
def refresh() -> dict[str, int]:
    return refresh_jobs()


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


@app.get("/stats/overview")
def overview() -> dict[str, Any]:
    ensure_seeded()
    jobs = db.list_jobs()
    return {
        "total": len(jobs),
        "high_matches": sum(1 for item in jobs if item["match_score"] >= 75),
        "medium_matches": sum(1 for item in jobs if 50 <= item["match_score"] < 75),
        "low_matches": sum(1 for item in jobs if item["match_score"] < 50),
        "by_status": {status: sum(1 for item in jobs if item["status"] == status) for status in sorted(db.VALID_STATUSES)},
    }


@app.get("/sources")
def sources() -> list[dict[str, Any]]:
    return load_sources()


@app.get("/profile")
def profile() -> dict[str, Any]:
    return load_profile()


@app.post("/sources")
def add_source(source: SourceIn) -> dict[str, Any]:
    try:
        saved = save_source(source.model_dump())
        db.upsert_source(saved)
        return saved
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
