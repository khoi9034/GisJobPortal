from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .freshness import apply_freshness, freshness_rules
from .paths import DB_PATH

VALID_STATUSES = {
    "new",
    "saved",
    "materials_generated",
    "ready_to_apply",
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
    "document_checklist",
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
    "application_packet_dir",
    "document_checklist",
    "source_posted_at",
    "source_updated_at",
    "source_closes_at",
    "first_seen_at",
    "last_seen_at",
    "last_checked_at",
    "posting_age_days",
    "freshness_bucket",
    "freshness_confidence",
    "is_stale",
    "is_closed_or_missing",
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
                recommended_resume_angle TEXT DEFAULT '',
                application_packet_dir TEXT DEFAULT '',
                document_checklist TEXT DEFAULT '{}',
                source_posted_at TEXT DEFAULT '',
                source_updated_at TEXT DEFAULT '',
                source_closes_at TEXT DEFAULT '',
                first_seen_at TEXT DEFAULT '',
                last_seen_at TEXT DEFAULT '',
                last_checked_at TEXT DEFAULT '',
                posting_age_days INTEGER,
                freshness_bucket TEXT DEFAULT 'unknown',
                freshness_confidence TEXT DEFAULT 'unknown',
                is_stale INTEGER NOT NULL DEFAULT 0,
                is_closed_or_missing INTEGER NOT NULL DEFAULT 0
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
                notes TEXT DEFAULT '',
                last_checked TEXT DEFAULT '',
                last_status TEXT DEFAULT '',
                jobs_found_last_run INTEGER NOT NULL DEFAULT 0,
                errors_last_run TEXT DEFAULT '',
                posted_date_supported INTEGER NOT NULL DEFAULT 0,
                close_date_supported INTEGER NOT NULL DEFAULT 0,
                updated_date_supported INTEGER NOT NULL DEFAULT 0,
                first_seen_only INTEGER NOT NULL DEFAULT 1
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
        ensure_job_columns(conn)
        ensure_source_columns(conn)


def ensure_job_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    additions = {
        "application_packet_dir": "TEXT DEFAULT ''",
        "document_checklist": "TEXT DEFAULT '{}'",
        "source_posted_at": "TEXT DEFAULT ''",
        "source_updated_at": "TEXT DEFAULT ''",
        "source_closes_at": "TEXT DEFAULT ''",
        "first_seen_at": "TEXT DEFAULT ''",
        "last_seen_at": "TEXT DEFAULT ''",
        "last_checked_at": "TEXT DEFAULT ''",
        "posting_age_days": "INTEGER",
        "freshness_bucket": "TEXT DEFAULT 'unknown'",
        "freshness_confidence": "TEXT DEFAULT 'unknown'",
        "is_stale": "INTEGER NOT NULL DEFAULT 0",
        "is_closed_or_missing": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, ddl in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")


def ensure_source_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(job_sources)").fetchall()}
    additions = {
        "last_checked": "TEXT DEFAULT ''",
        "last_status": "TEXT DEFAULT ''",
        "jobs_found_last_run": "INTEGER NOT NULL DEFAULT 0",
        "errors_last_run": "TEXT DEFAULT ''",
        "posted_date_supported": "INTEGER NOT NULL DEFAULT 0",
        "close_date_supported": "INTEGER NOT NULL DEFAULT 0",
        "updated_date_supported": "INTEGER NOT NULL DEFAULT 0",
        "first_seen_only": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, ddl in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE job_sources ADD COLUMN {column} {ddl}")


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True)


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    for field in JSON_FIELDS:
        value = job.get(field)
        if isinstance(value, str):
            try:
                job[field] = json.loads(value) if value else ({} if field in {"scoring_breakdown", "document_checklist"} else [])
            except json.JSONDecodeError:
                job[field] = {} if field in {"scoring_breakdown", "document_checklist"} else []
    for field in ("is_stale", "is_closed_or_missing"):
        job[field] = bool(job.get(field))
    return job


def upsert_source(source: dict[str, Any], path: Path | str = DB_PATH) -> None:
    init_db(path)
    with connection(path) as conn:
        conn.execute(
            """
            INSERT INTO job_sources (
                name, type, url, enabled, notes, posted_date_supported,
                close_date_supported, updated_date_supported, first_seen_only
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                type=excluded.type,
                url=excluded.url,
                enabled=excluded.enabled,
                notes=excluded.notes,
                posted_date_supported=excluded.posted_date_supported,
                close_date_supported=excluded.close_date_supported,
                updated_date_supported=excluded.updated_date_supported,
                first_seen_only=excluded.first_seen_only
            """,
            (
                source["name"],
                source["type"],
                source["url"],
                int(bool(source.get("enabled", True))),
                source.get("notes", ""),
                int(bool(source.get("posted_date_supported", False))),
                int(bool(source.get("close_date_supported", False))),
                int(bool(source.get("updated_date_supported", False))),
                int(bool(source.get("first_seen_only", True))),
            ),
        )


def mark_source_checked(
    name: str,
    status: str,
    path: Path | str = DB_PATH,
    jobs_found: int | None = None,
    error: str = "",
) -> None:
    init_db(path)
    with connection(path) as conn:
        conn.execute(
            """
            UPDATE job_sources
            SET last_checked = ?, last_status = ?,
                jobs_found_last_run = COALESCE(?, jobs_found_last_run),
                errors_last_run = ?
            WHERE name = ?
            """,
            (datetime.now(UTC).isoformat(), status, jobs_found, error, name),
        )


def list_sources(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(path)
    with connection(path) as conn:
        rows = conn.execute("SELECT * FROM job_sources ORDER BY name").fetchall()
    bool_fields = {"enabled", "posted_date_supported", "close_date_supported", "updated_date_supported", "first_seen_only"}
    return [{**dict(row), **{field: bool(row[field]) for field in bool_fields if field in row.keys()}} for row in rows]


def duplicate_key(job: dict[str, Any]) -> tuple[str, str, str, str]:
    key_url = (job.get("source_url") or job.get("apply_url") or "").strip().lower()
    return (
        str(job.get("company", "")).strip().lower(),
        str(job.get("title", "")).strip().lower(),
        str(job.get("location", "")).strip().lower(),
        key_url,
    )


def duplicate_row(conn: sqlite3.Connection, job: dict[str, Any]) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM jobs
        WHERE lower(trim(company)) = ?
          AND lower(trim(title)) = ?
          AND lower(trim(location)) = ?
          AND lower(trim(coalesce(nullif(source_url, ''), apply_url, ''))) = ?
        """,
        duplicate_key(job),
    ).fetchone()


def insert_job(job: dict[str, Any], path: Path | str = DB_PATH) -> tuple[int | None, bool]:
    init_db(path)
    values = {column: job.get(column) for column in JOB_COLUMNS}
    values["date_found"] = values.get("date_found") or now_iso()
    values = {**values, **apply_freshness(values)}
    values["status"] = values.get("status") or "new"
    values["match_score"] = int(values.get("match_score") or 0)
    values["is_stale"] = int(bool(values.get("is_stale")))
    values["is_closed_or_missing"] = int(bool(values.get("is_closed_or_missing")))
    for field in JSON_FIELDS:
        if values.get(field) is None:
            values[field] = {} if field in {"scoring_breakdown", "document_checklist"} else []
        values[field] = dumps(values.get(field))

    columns = ", ".join(JOB_COLUMNS)
    placeholders = ", ".join("?" for _ in JOB_COLUMNS)
    with connection(path) as conn:
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO jobs ({columns}) VALUES ({placeholders})",
            [values[column] for column in JOB_COLUMNS],
        )
        if cursor.rowcount == 0:
            existing = duplicate_row(conn, values)
            if not existing:
                return None, True
            first_seen = existing["first_seen_at"] or existing["date_found"]
            updated = {**values, **apply_freshness(values, first_seen_at=first_seen)}
            for field in JSON_FIELDS:
                if not isinstance(updated.get(field), str):
                    updated[field] = dumps(updated.get(field))
            updated["is_stale"] = int(bool(updated.get("is_stale")))
            updated["is_closed_or_missing"] = int(bool(updated.get("is_closed_or_missing")))
            update_fields = [
                field for field in JOB_COLUMNS
                if field not in {
                    "status",
                    "date_found",
                    "first_seen_at",
                    "notes",
                    "generated_cover_letter",
                    "generated_followup_email",
                    "recruiter_message",
                    "resume_bullet_suggestions",
                    "application_packet_dir",
                    "document_checklist",
                }
            ]
            conn.execute(
                f"UPDATE jobs SET {', '.join(f'{field} = ?' for field in update_fields)} WHERE id = ?",
                [updated.get(field) for field in update_fields] + [existing["id"]],
            )
            return int(existing["id"]), True
        return int(cursor.lastrowid), False


def list_jobs(status: str | None = None, path: Path | str = DB_PATH, active_only: bool = False) -> list[dict[str, Any]]:
    init_db(path)
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    if active_only:
        rules = freshness_rules()
        sql += " AND" if params else " WHERE"
        sql += " is_closed_or_missing = 0 AND (posting_age_days IS NULL OR posting_age_days <= ? OR match_score >= 85)"
        params.append(int(rules["hide_after_days"]))
    sql += """
        ORDER BY match_score DESC,
            coalesce(nullif(source_posted_at, ''), first_seen_at, date_found) DESC,
            CASE WHEN source_closes_at = '' THEN '9999-12-31' ELSE source_closes_at END ASC,
            first_seen_at DESC,
            id DESC
    """
    with connection(path) as conn:
        return [row_to_job(row) for row in conn.execute(sql, params).fetchall()]


def mark_missing_jobs(source: str, checked_at: str, seen_jobs: list[dict[str, Any]], path: Path | str = DB_PATH) -> int:
    init_db(path)
    seen = {duplicate_key(job) for job in seen_jobs}
    with connection(path) as conn:
        rows = conn.execute("SELECT id, title, company, location, source_url, apply_url FROM jobs WHERE source = ?", (source,)).fetchall()
        missing_ids = [row["id"] for row in rows if duplicate_key(dict(row)) not in seen]
        for job_id in missing_ids:
            conn.execute("UPDATE jobs SET is_closed_or_missing = 1, last_checked_at = ? WHERE id = ?", (checked_at, job_id))
        return len(missing_ids)


def freshness_counts(path: Path | str = DB_PATH) -> dict[str, int]:
    rules = freshness_rules()
    init_db(path)
    with connection(path) as conn:
        row = conn.execute(
            """
            SELECT
                sum(CASE WHEN is_stale = 1 THEN 1 ELSE 0 END) AS stale_jobs,
                sum(CASE WHEN is_closed_or_missing = 0 AND posting_age_days IS NOT NULL AND posting_age_days <= ? THEN 1 ELSE 0 END) AS fresh_jobs,
                sum(CASE WHEN source_closes_at <> '' AND is_closed_or_missing = 0 AND julianday(source_closes_at) - julianday(date('now')) BETWEEN 0 AND ? THEN 1 ELSE 0 END) AS closing_soon_jobs
            FROM jobs
            """,
            (int(rules["fresh_days"]), int(rules["closing_soon_days"])),
        ).fetchone()
    return {key: int(row[key] or 0) for key in ("stale_jobs", "fresh_jobs", "closing_soon_jobs")}


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
            values[field] = {} if field in {"scoring_breakdown", "document_checklist"} else []
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
