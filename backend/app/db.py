from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import DB_PATH

VALID_STATUSES = {
    "new",
    "saved",
    "skipped",
    "applied",
    "interview",
    "rejected",
    "follow_up_needed",
}

JSON_FIELDS = {
    "scoring_breakdown",
    "fit_reasons",
    "missing_skills",
    "keyword_matches",
    "resume_bullet_suggestions",
}

JOB_COLUMNS = [
    "title",
    "company",
    "location",
    "remote_status",
    "source",
    "source_url",
    "apply_url",
    "description",
    "requirements",
    "salary_min",
    "salary_max",
    "date_posted",
    "date_found",
    "status",
    "match_score",
    "fit_summary",
    "missing_skills",
    "generated_cover_letter",
    "generated_followup_email",
    "recruiter_message",
    "resume_bullet_suggestions",
    "notes",
    "scoring_breakdown",
    "fit_reasons",
    "keyword_matches",
    "recommended_resume_angle",
]


def now_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection(path: Path | str = DB_PATH):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | str = DB_PATH) -> None:
    with connection(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                remote_status TEXT DEFAULT '',
                source TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                apply_url TEXT DEFAULT '',
                description TEXT DEFAULT '',
                requirements TEXT DEFAULT '',
                salary_min REAL,
                salary_max REAL,
                date_posted TEXT DEFAULT '',
                date_found TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                match_score INTEGER NOT NULL DEFAULT 0,
                fit_summary TEXT DEFAULT '',
                missing_skills TEXT DEFAULT '[]',
                generated_cover_letter TEXT DEFAULT '',
                generated_followup_email TEXT DEFAULT '',
                recruiter_message TEXT DEFAULT '',
                resume_bullet_suggestions TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                scoring_breakdown TEXT DEFAULT '{}',
                fit_reasons TEXT DEFAULT '[]',
                keyword_matches TEXT DEFAULT '[]',
                recommended_resume_angle TEXT DEFAULT ''
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_duplicate
            ON jobs (
                lower(trim(company)),
                lower(trim(title)),
                lower(trim(location)),
                lower(trim(coalesce(nullif(source_url, ''), apply_url, '')))
            );

            CREATE TABLE IF NOT EXISTS job_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS application_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL UNIQUE,
                fit_summary TEXT DEFAULT '',
                cover_letter TEXT DEFAULT '',
                followup_email TEXT DEFAULT '',
                recruiter_message TEXT DEFAULT '',
                resume_bullets TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS application_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS profile_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True)


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    for field in JSON_FIELDS:
        value = job.get(field)
        if isinstance(value, str):
            try:
                job[field] = json.loads(value) if value else ([] if field != "scoring_breakdown" else {})
            except json.JSONDecodeError:
                job[field] = [] if field != "scoring_breakdown" else {}
    return job


def upsert_source(source: dict[str, Any], path: Path | str = DB_PATH) -> None:
    init_db(path)
    with connection(path) as conn:
        conn.execute(
            """
            INSERT INTO job_sources (name, type, url, enabled, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                type=excluded.type,
                url=excluded.url,
                enabled=excluded.enabled,
                notes=excluded.notes
            """,
            (
                source["name"],
                source["type"],
                source["url"],
                int(bool(source.get("enabled", True))),
                source.get("notes", ""),
            ),
        )


def insert_job(job: dict[str, Any], path: Path | str = DB_PATH) -> tuple[int | None, bool]:
    init_db(path)
    values = {column: job.get(column) for column in JOB_COLUMNS}
    values["date_found"] = values.get("date_found") or now_iso()
    values["status"] = values.get("status") or "new"
    values["match_score"] = int(values.get("match_score") or 0)
    for field in JSON_FIELDS:
        if values.get(field) is None:
            values[field] = {} if field == "scoring_breakdown" else []
        values[field] = dumps(values.get(field))

    columns = ", ".join(JOB_COLUMNS)
    placeholders = ", ".join("?" for _ in JOB_COLUMNS)
    with connection(path) as conn:
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO jobs ({columns}) VALUES ({placeholders})",
            [values[column] for column in JOB_COLUMNS],
        )
        if cursor.rowcount == 0:
            return None, True
        return int(cursor.lastrowid), False


def list_jobs(status: str | None = None, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(path)
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY match_score DESC, date_found DESC, id DESC"
    with connection(path) as conn:
        return [row_to_job(row) for row in conn.execute(sql, params).fetchall()]


def get_job(job_id: int, path: Path | str = DB_PATH) -> dict[str, Any] | None:
    init_db(path)
    with connection(path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row) if row else None


def update_job_fields(job_id: int, fields: dict[str, Any], path: Path | str = DB_PATH) -> dict[str, Any]:
    if not fields:
        raise ValueError("No fields to update")
    allowed = set(JOB_COLUMNS) - {"date_found"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unsupported job fields: {', '.join(sorted(bad))}")
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")

    values = dict(fields)
    for field in JSON_FIELDS & set(values):
        if values.get(field) is None:
            values[field] = {} if field == "scoring_breakdown" else []
        values[field] = dumps(values[field])
    assignments = ", ".join(f"{field} = ?" for field in values)

    init_db(path)
    with connection(path) as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", [*values.values(), job_id])
        if "status" in fields:
            conn.execute(
                "INSERT INTO application_events (job_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                (job_id, "status", fields["status"], datetime.now(UTC).isoformat()),
            )
    job = get_job(job_id, path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    return job


def save_materials(job_id: int, materials: dict[str, Any], path: Path | str = DB_PATH) -> dict[str, Any]:
    updated = update_job_fields(
        job_id,
        {
            "fit_summary": materials["fit_summary"],
            "generated_cover_letter": materials["cover_letter"],
            "generated_followup_email": materials["followup_email"],
            "recruiter_message": materials["recruiter_message"],
            "resume_bullet_suggestions": materials["resume_bullets"],
        },
        path,
    )
    with connection(path) as conn:
        conn.execute(
            """
            INSERT INTO application_materials
                (job_id, fit_summary, cover_letter, followup_email, recruiter_message, resume_bullets, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                fit_summary=excluded.fit_summary,
                cover_letter=excluded.cover_letter,
                followup_email=excluded.followup_email,
                recruiter_message=excluded.recruiter_message,
                resume_bullets=excluded.resume_bullets,
                created_at=excluded.created_at
            """,
            (
                job_id,
                materials["fit_summary"],
                materials["cover_letter"],
                materials["followup_email"],
                materials["recruiter_message"],
                dumps(materials["resume_bullets"]),
                datetime.now(UTC).isoformat(),
            ),
        )
    return updated
