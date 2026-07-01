from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .freshness import apply_freshness, freshness_rules, parse_date, today_utc
from .paths import DB_PATH, database_type, postgres_connection_url

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

VALID_REVIEW_STATUSES = {"unreviewed", "interested", "not_interested", "maybe", "applied", "archived"}
VALID_PRIORITY_BUCKETS = {"urgent", "high", "medium", "low"}
VALID_APPLICATION_METHODS = {"", "employer_portal", "email", "referral", "recruiter", "other"}
VALID_OUTCOME_STATUSES = {"not_started", "ready_to_apply", "applied", "follow_up_due", "interview", "rejected", "closed", "withdrawn"}
SAMPLE_JOB_SOURCE = "Sample GIS Jobs"

JSON_FIELDS = {
    "scoring_breakdown",
    "fit_reasons",
    "missing_skills",
    "keyword_matches",
    "positive_matches",
    "penalty_matches",
    "resume_bullet_suggestions",
    "document_checklist",
    "apply_options_json",
    "blocker_resolutions_json",
    "application_packet_files_json",
    "packet_qa_notes",
}

JOB_COLUMNS = [
    "title",
    "company",
    "location",
    "country",
    "region",
    "international_region",
    "work_authorization_note",
    "language_requirement",
    "relocation_required",
    "timezone_note",
    "remote_status",
    "source",
    "source_url",
    "apply_url",
    "external_job_id",
    "external_id",
    "employer_website",
    "employer_logo",
    "employment_type",
    "apply_is_direct",
    "apply_options_json",
    "link_status",
    "original_source",
    "attribution_note",
    "description_hash",
    "description",
    "requirements",
    "salary_min",
    "salary_max",
    "city",
    "state",
    "latitude",
    "longitude",
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
    "positive_matches",
    "penalty_matches",
    "score_reason",
    "score_band",
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
    "reviewed_at",
    "review_status",
    "review_notes",
    "priority_bucket",
    "close_days_remaining",
    "needs_packet",
    "packet_generated_at",
    "application_packet_files_json",
    "packet_qa_status",
    "packet_qa_notes",
    "is_stale",
    "is_closed_or_missing",
    "application_url_opened_at",
    "application_started_at",
    "applied_at",
    "follow_up_due_at",
    "follow_up_sent_at",
    "application_method",
    "application_contact_name",
    "application_contact_email",
    "application_confirmation_number",
    "application_submission_notes",
    "outcome_status",
    "blocker_resolutions_json",
    "blocker_reviewed_at",
    "blocker_review_notes",
    "manual_apply_override",
    "manual_apply_override_reason",
]


def now_iso() -> str:
    return datetime.now(UTC).date().isoformat()


class PostgresConnection:
    is_postgres = True

    def __init__(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres DATABASE_URL requires psycopg; run pip install -r requirements.txt") from exc
        self.conn = psycopg.connect(postgres_connection_url(), row_factory=dict_row)

    def execute(self, sql: str, params: Any = None):
        return self.conn.execute(sql.replace("?", "%s"), params or [])

    def executescript(self, script: str) -> None:
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            self.execute(statement)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def uses_configured_database(path: Path | str = DB_PATH) -> bool:
    return Path(path) == Path(DB_PATH)


def is_postgres_conn(conn: Any) -> bool:
    return bool(getattr(conn, "is_postgres", False))


def connect(path: Path | str = DB_PATH):
    if uses_configured_database(path) and database_type() == "postgres":
        return PostgresConnection()
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
        schema = """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                country TEXT DEFAULT '',
                region TEXT DEFAULT '',
                international_region TEXT DEFAULT '',
                work_authorization_note TEXT DEFAULT '',
                language_requirement TEXT DEFAULT '',
                relocation_required TEXT DEFAULT '',
                timezone_note TEXT DEFAULT '',
                remote_status TEXT DEFAULT '',
                source TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                apply_url TEXT DEFAULT '',
                external_job_id TEXT DEFAULT '',
                external_id TEXT DEFAULT '',
                employer_website TEXT DEFAULT '',
                employer_logo TEXT DEFAULT '',
                employment_type TEXT DEFAULT '',
                apply_is_direct INTEGER NOT NULL DEFAULT 0,
                apply_options_json TEXT DEFAULT '[]',
                link_status TEXT DEFAULT 'missing',
                original_source TEXT DEFAULT '',
                attribution_note TEXT DEFAULT '',
                description_hash TEXT DEFAULT '',
                description TEXT DEFAULT '',
                requirements TEXT DEFAULT '',
                salary_min REAL,
                salary_max REAL,
                city TEXT DEFAULT '',
                state TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
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
                positive_matches TEXT DEFAULT '[]',
                penalty_matches TEXT DEFAULT '[]',
                score_reason TEXT DEFAULT '',
                score_band TEXT DEFAULT '',
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
                reviewed_at TEXT DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'unreviewed',
                review_notes TEXT DEFAULT '',
                priority_bucket TEXT NOT NULL DEFAULT 'medium',
                close_days_remaining INTEGER,
                needs_packet INTEGER NOT NULL DEFAULT 1,
                packet_generated_at TEXT DEFAULT '',
                application_packet_files_json TEXT DEFAULT '{}',
                packet_qa_status TEXT DEFAULT '',
                packet_qa_notes TEXT DEFAULT '[]',
                is_stale INTEGER NOT NULL DEFAULT 0,
                is_closed_or_missing INTEGER NOT NULL DEFAULT 0,
                application_url_opened_at TEXT DEFAULT '',
                application_started_at TEXT DEFAULT '',
                applied_at TEXT DEFAULT '',
                follow_up_due_at TEXT DEFAULT '',
                follow_up_sent_at TEXT DEFAULT '',
                application_method TEXT DEFAULT '',
                application_contact_name TEXT DEFAULT '',
                application_contact_email TEXT DEFAULT '',
                application_confirmation_number TEXT DEFAULT '',
                application_submission_notes TEXT DEFAULT '',
                outcome_status TEXT NOT NULL DEFAULT 'not_started',
                blocker_resolutions_json TEXT DEFAULT '{}',
                blocker_reviewed_at TEXT DEFAULT '',
                blocker_review_notes TEXT DEFAULT '',
                manual_apply_override INTEGER NOT NULL DEFAULT 0,
                manual_apply_override_reason TEXT DEFAULT ''
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
                last_success_at TEXT DEFAULT '',
                validation_status TEXT DEFAULT '',
                last_validated_at TEXT DEFAULT '',
                jobs_sampled INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                source TEXT DEFAULT '',
                summary_json TEXT DEFAULT '{}',
                report_markdown TEXT DEFAULT ''
            );
            """
        if is_postgres_conn(conn):
            schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        conn.executescript(schema)
        ensure_job_columns(conn)
        ensure_source_columns(conn)


def table_columns(conn: Any, table: str) -> set[str]:
    if is_postgres_conn(conn):
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {row["name"] for row in rows}
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_job_columns(conn: Any) -> None:
    existing = table_columns(conn, "jobs")
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
        "reviewed_at": "TEXT DEFAULT ''",
        "review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
        "review_notes": "TEXT DEFAULT ''",
        "priority_bucket": "TEXT NOT NULL DEFAULT 'medium'",
        "close_days_remaining": "INTEGER",
        "needs_packet": "INTEGER NOT NULL DEFAULT 1",
        "packet_generated_at": "TEXT DEFAULT ''",
        "application_packet_files_json": "TEXT DEFAULT '{}'",
        "packet_qa_status": "TEXT DEFAULT ''",
        "packet_qa_notes": "TEXT DEFAULT '[]'",
        "is_stale": "INTEGER NOT NULL DEFAULT 0",
        "is_closed_or_missing": "INTEGER NOT NULL DEFAULT 0",
        "positive_matches": "TEXT DEFAULT '[]'",
        "penalty_matches": "TEXT DEFAULT '[]'",
        "score_reason": "TEXT DEFAULT ''",
        "score_band": "TEXT DEFAULT ''",
        "application_url_opened_at": "TEXT DEFAULT ''",
        "application_started_at": "TEXT DEFAULT ''",
        "applied_at": "TEXT DEFAULT ''",
        "follow_up_due_at": "TEXT DEFAULT ''",
        "follow_up_sent_at": "TEXT DEFAULT ''",
        "application_method": "TEXT DEFAULT ''",
        "application_contact_name": "TEXT DEFAULT ''",
        "application_contact_email": "TEXT DEFAULT ''",
        "application_confirmation_number": "TEXT DEFAULT ''",
        "application_submission_notes": "TEXT DEFAULT ''",
        "outcome_status": "TEXT NOT NULL DEFAULT 'not_started'",
        "blocker_resolutions_json": "TEXT DEFAULT '{}'",
        "blocker_reviewed_at": "TEXT DEFAULT ''",
        "blocker_review_notes": "TEXT DEFAULT ''",
        "manual_apply_override": "INTEGER NOT NULL DEFAULT 0",
        "manual_apply_override_reason": "TEXT DEFAULT ''",
        "external_job_id": "TEXT DEFAULT ''",
        "external_id": "TEXT DEFAULT ''",
        "employer_website": "TEXT DEFAULT ''",
        "employer_logo": "TEXT DEFAULT ''",
        "employment_type": "TEXT DEFAULT ''",
        "apply_is_direct": "INTEGER NOT NULL DEFAULT 0",
        "apply_options_json": "TEXT DEFAULT '[]'",
        "link_status": "TEXT DEFAULT 'missing'",
        "original_source": "TEXT DEFAULT ''",
        "attribution_note": "TEXT DEFAULT ''",
        "description_hash": "TEXT DEFAULT ''",
        "city": "TEXT DEFAULT ''",
        "state": "TEXT DEFAULT ''",
        "latitude": "REAL",
        "longitude": "REAL",
        "country": "TEXT DEFAULT ''",
        "region": "TEXT DEFAULT ''",
        "international_region": "TEXT DEFAULT ''",
        "work_authorization_note": "TEXT DEFAULT ''",
        "language_requirement": "TEXT DEFAULT ''",
        "relocation_required": "TEXT DEFAULT ''",
        "timezone_note": "TEXT DEFAULT ''",
    }
    for column, ddl in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")


def ensure_source_columns(conn: Any) -> None:
    existing = table_columns(conn, "job_sources")
    additions = {
        "last_checked": "TEXT DEFAULT ''",
        "last_status": "TEXT DEFAULT ''",
        "last_success_at": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT ''",
        "last_validated_at": "TEXT DEFAULT ''",
        "jobs_sampled": "INTEGER NOT NULL DEFAULT 0",
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
                job[field] = json.loads(value) if value else ({} if field in {"scoring_breakdown", "document_checklist", "blocker_resolutions_json", "application_packet_files_json"} else [])
            except json.JSONDecodeError:
                job[field] = {} if field in {"scoring_breakdown", "document_checklist", "blocker_resolutions_json", "application_packet_files_json"} else []
    for field in ("is_stale", "is_closed_or_missing", "needs_packet", "manual_apply_override"):
        job[field] = bool(job.get(field))
    job["apply_is_direct"] = bool(job.get("apply_is_direct"))
    return job


def priority_for_job(job: dict[str, Any]) -> str:
    days = job.get("close_days_remaining")
    score = int(job.get("match_score") or 0)
    if score >= 70:
        return "high"
    if isinstance(days, int) and 0 <= days <= 7 and score >= 55:
        return "urgent"
    if score >= 55:
        return "medium"
    return "low"


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
        success_at = datetime.now(UTC).isoformat() if not error and status.startswith("ok:") else None
        conn.execute(
            """
            UPDATE job_sources
            SET last_checked = ?, last_status = ?,
                last_success_at = COALESCE(?, last_success_at),
                jobs_found_last_run = COALESCE(?, jobs_found_last_run),
                errors_last_run = ?
            WHERE name = ?
            """,
            (datetime.now(UTC).isoformat(), status, success_at, jobs_found, error, name),
        )


def list_sources(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    init_db(path)
    with connection(path) as conn:
        rows = conn.execute("SELECT * FROM job_sources ORDER BY name").fetchall()
    bool_fields = {"enabled", "posted_date_supported", "close_date_supported", "updated_date_supported", "first_seen_only"}
    sources = []
    for row in rows:
        item = {**dict(row), **{field: bool(row[field]) for field in bool_fields if field in row.keys()}}
        item.update(
            {
                "supports_posted_date": item.get("posted_date_supported", False),
                "supports_close_date": item.get("close_date_supported", False),
                "supports_updated_date": item.get("updated_date_supported", False),
                "freshness_confidence_default": "first_seen_only" if item.get("first_seen_only") else "source_posted_date",
                "status": item.get("validation_status") or ("enabled" if item.get("enabled") else "disabled"),
                "last_checked_at": item.get("last_checked", ""),
                "last_error": item.get("errors_last_run", ""),
            }
        )
        sources.append(item)
    return sources


def record_source_validation(source: dict[str, Any], summary: dict[str, Any], path: Path | str = DB_PATH) -> None:
    upsert_source(source, path)
    with connection(path) as conn:
        conn.execute(
            """
            UPDATE job_sources
            SET validation_status = ?, last_validated_at = ?, jobs_sampled = ?,
                jobs_found_last_run = ?, errors_last_run = ?
            WHERE name = ?
            """,
            (
                summary.get("validation_status", ""),
                summary.get("last_validated_at", ""),
                int(summary.get("jobs_sampled") or 0),
                int(summary.get("jobs_found_last_run") or summary.get("jobs_sampled") or 0),
                summary.get("last_error", ""),
                source["name"],
            ),
        )


def save_daily_report(report_date: str, generated_at: str, source: str, summary: dict[str, Any], markdown: str, path: Path | str = DB_PATH) -> None:
    init_db(path)
    with connection(path) as conn:
        conn.execute(
            """
            INSERT INTO daily_reports (report_date, generated_at, source, summary_json, report_markdown)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_date, generated_at, source, dumps(summary), markdown),
        )


def latest_daily_report(path: Path | str = DB_PATH) -> dict[str, Any]:
    init_db(path)
    with connection(path) as conn:
        row = conn.execute("SELECT * FROM daily_reports ORDER BY generated_at DESC, id DESC LIMIT 1").fetchone()
    if not row:
        return {"exists": False, "date": "", "text": "No hosted report generated yet.", "summary": {}}
    item = dict(row)
    try:
        summary = json.loads(item.get("summary_json") or "{}")
    except json.JSONDecodeError:
        summary = {}
    return {"exists": True, "date": item.get("report_date", ""), "text": item.get("report_markdown", ""), "summary": summary, "source": item.get("source", "")}


def canonical_job_url(job: dict[str, Any]) -> str:
    source_url = str(job.get("source_url") or "").strip()
    apply_url = str(job.get("apply_url") or "").strip()
    source_text = f"{job.get('source', '')} {job.get('attribution_note', '')}".lower()
    prefer_apply = apply_url and any(provider in source_text for provider in ("adzuna", "jsearch", "serpapi", "remotive", "rapidapi"))
    raw = apply_url if prefer_apply else source_url or apply_url
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.netloc:
        return raw.lower()
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/").lower()
    return urlunsplit(((parts.scheme or "https").lower(), netloc, path, "", ""))


def description_fingerprint(job: dict[str, Any]) -> str:
    text = " ".join(str(job.get(field, "")) for field in ("description", "requirements")).strip().lower()
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text else ""


def duplicate_key(job: dict[str, Any]) -> tuple[str, str, str, str]:
    key_url = canonical_job_url(job)
    fallback = (
        key_url
        or str(job.get("external_job_id") or job.get("external_id") or "").strip().lower()
        or str(job.get("description_hash") or "").strip().lower()
        or description_fingerprint(job)
    )
    return (
        str(job.get("company", "")).strip().lower(),
        str(job.get("title", "")).strip().lower(),
        str(job.get("location", "")).strip().lower(),
        fallback,
    )


def duplicate_row(conn: sqlite3.Connection, job: dict[str, Any]) -> sqlite3.Row | None:
    company, title, location, _ = duplicate_key(job)
    rows = conn.execute(
        """
        SELECT * FROM jobs
        WHERE lower(trim(company)) = ?
          AND lower(trim(title)) = ?
          AND lower(trim(location)) = ?
        """,
        (company, title, location),
    ).fetchall()
    wanted = duplicate_key(job)
    return next((row for row in rows if duplicate_key(dict(row)) == wanted), None)


def insert_job(job: dict[str, Any], path: Path | str = DB_PATH) -> tuple[int | None, bool]:
    init_db(path)
    values = {column: job.get(column) for column in JOB_COLUMNS}
    values["description_hash"] = values.get("description_hash") or description_fingerprint(values)
    values["date_found"] = values.get("date_found") or now_iso()
    values = {**values, **apply_freshness(values)}
    values["status"] = values.get("status") or "new"
    values["match_score"] = int(values.get("match_score") or 0)
    values["review_status"] = values.get("review_status") or "unreviewed"
    values["priority_bucket"] = values.get("priority_bucket") or priority_for_job(values)
    values["outcome_status"] = values.get("outcome_status") or "not_started"
    values["manual_apply_override"] = int(bool(values.get("manual_apply_override")))
    values["manual_apply_override_reason"] = values.get("manual_apply_override_reason") or ""
    values["blocker_reviewed_at"] = values.get("blocker_reviewed_at") or ""
    values["blocker_review_notes"] = values.get("blocker_review_notes") or ""
    values["link_status"] = values.get("link_status") or ("available" if values.get("apply_url") else "source_only" if values.get("source_url") else "missing")
    values["apply_is_direct"] = int(bool(values.get("apply_is_direct")))
    for field in (
        "application_url_opened_at",
        "application_started_at",
        "applied_at",
        "follow_up_due_at",
        "follow_up_sent_at",
        "application_method",
        "application_contact_name",
        "application_contact_email",
        "application_confirmation_number",
        "application_submission_notes",
    ):
        values[field] = values.get(field) or ""
    values["needs_packet"] = int(bool(values.get("needs_packet", True)))
    values["is_stale"] = int(bool(values.get("is_stale")))
    values["is_closed_or_missing"] = int(bool(values.get("is_closed_or_missing")))
    for field in JSON_FIELDS:
        if values.get(field) is None:
            values[field] = {} if field in {"scoring_breakdown", "document_checklist", "blocker_resolutions_json", "application_packet_files_json"} else []
        values[field] = dumps(values.get(field))

    columns = ", ".join(JOB_COLUMNS)
    placeholders = ", ".join("?" for _ in JOB_COLUMNS)
    with connection(path) as conn:
        existing = duplicate_row(conn, values)
        if existing:
            first_seen = existing["first_seen_at"] or existing["date_found"]
            updated = {**values, **apply_freshness(values, first_seen_at=first_seen)}
            for field in JSON_FIELDS:
                if not isinstance(updated.get(field), str):
                    updated[field] = dumps(updated.get(field))
            updated["is_stale"] = int(bool(updated.get("is_stale")))
            updated["is_closed_or_missing"] = int(bool(updated.get("is_closed_or_missing")))
            updated["apply_is_direct"] = int(bool(updated.get("apply_is_direct")))
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
                    "reviewed_at",
                    "review_status",
                    "review_notes",
                    "priority_bucket",
                    "needs_packet",
                    "packet_generated_at",
                    "application_packet_files_json",
                    "packet_qa_status",
                    "packet_qa_notes",
                    "application_url_opened_at",
                    "application_started_at",
                    "applied_at",
                    "follow_up_due_at",
                    "follow_up_sent_at",
                    "application_method",
                    "application_contact_name",
                    "application_contact_email",
                    "application_confirmation_number",
                    "application_submission_notes",
                    "outcome_status",
                    "blocker_resolutions_json",
                    "blocker_reviewed_at",
                    "blocker_review_notes",
                    "manual_apply_override",
                    "manual_apply_override_reason",
                }
            ]
            conn.execute(
                f"UPDATE jobs SET {', '.join(f'{field} = ?' for field in update_fields)} WHERE id = ?",
                [updated.get(field) for field in update_fields] + [existing["id"]],
            )
            return int(existing["id"]), True
        sql = f"INSERT INTO jobs ({columns}) VALUES ({placeholders})"
        if is_postgres_conn(conn):
            row = conn.execute(f"{sql} RETURNING id", [values[column] for column in JOB_COLUMNS]).fetchone()
            return int(row["id"]), False
        cursor = conn.execute(sql, [values[column] for column in JOB_COLUMNS])
        return int(cursor.lastrowid), False


def list_jobs(status: str | None = None, path: Path | str = DB_PATH, active_only: bool = False, include_sample: bool = True) -> list[dict[str, Any]]:
    init_db(path)
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    if not include_sample:
        sql += " AND" if params else " WHERE"
        sql += " source != ?"
        params.append(SAMPLE_JOB_SOURCE)
    if active_only:
        rules = freshness_rules()
        sql += " AND" if params else " WHERE"
        sql += " is_closed_or_missing = 0 AND (posting_age_days IS NULL OR posting_age_days <= ? OR match_score >= 85)"
        params.append(int(rules["hide_after_days"]))
    sql += """
        ORDER BY match_score DESC,
            CASE WHEN source_closes_at = '' THEN '9999-12-31' ELSE source_closes_at END ASC,
            coalesce(nullif(source_posted_at, ''), first_seen_at, date_found) DESC,
            CASE WHEN freshness_confidence = 'source_posted_date' THEN 0 ELSE 1 END ASC,
            first_seen_at DESC,
            id DESC
    """
    with connection(path) as conn:
        return [row_to_job(row) for row in conn.execute(sql, params).fetchall()]


def mark_missing_jobs(source: str, checked_at: str, seen_jobs: list[dict[str, Any]], path: Path | str = DB_PATH) -> int:
    init_db(path)
    seen = {duplicate_key(job) for job in seen_jobs}
    with connection(path) as conn:
        rows = conn.execute("SELECT id, title, company, location, source, attribution_note, source_url, apply_url, external_job_id, external_id, description_hash FROM jobs WHERE source = ?", (source,)).fetchall()
        missing_ids = [row["id"] for row in rows if duplicate_key(dict(row)) not in seen]
        for job_id in missing_ids:
            conn.execute("UPDATE jobs SET is_closed_or_missing = 1, last_checked_at = ? WHERE id = ?", (checked_at, job_id))
        return len(missing_ids)


def freshness_counts(path: Path | str = DB_PATH, include_sample: bool = True) -> dict[str, int]:
    rules = freshness_rules()
    rows = list_jobs(path=path, include_sample=include_sample)
    closing_soon = 0
    for job in rows:
        closes = parse_date(job.get("source_closes_at"))
        if closes and not job.get("is_closed_or_missing"):
            days = (closes - today_utc()).days
            closing_soon += int(0 <= days <= int(rules["closing_soon_days"]))
    return {
        "stale_jobs": sum(1 for job in rows if job.get("is_stale")),
        "fresh_jobs": sum(1 for job in rows if not job.get("is_closed_or_missing") and job.get("posting_age_days") is not None and int(job["posting_age_days"]) <= int(rules["fresh_days"])),
        "closing_soon_jobs": closing_soon,
    }


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
    if "review_status" in fields and fields["review_status"] not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {fields['review_status']}")
    if "priority_bucket" in fields and fields["priority_bucket"] not in VALID_PRIORITY_BUCKETS:
        raise ValueError(f"Invalid priority bucket: {fields['priority_bucket']}")
    if "application_method" in fields and fields["application_method"] not in VALID_APPLICATION_METHODS:
        raise ValueError(f"Invalid application method: {fields['application_method']}")
    if "outcome_status" in fields and fields["outcome_status"] not in VALID_OUTCOME_STATUSES:
        raise ValueError(f"Invalid outcome status: {fields['outcome_status']}")

    values = dict(fields)
    for field in JSON_FIELDS & set(values):
        if values.get(field) is None:
            values[field] = {} if field in {"scoring_breakdown", "document_checklist", "blocker_resolutions_json", "application_packet_files_json"} else []
        values[field] = dumps(values[field])
    for field in ("is_stale", "is_closed_or_missing", "needs_packet", "manual_apply_override", "apply_is_direct"):
        if field in values and values[field] is not None:
            values[field] = int(bool(values[field]))
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


def close_days(job: dict[str, Any]) -> int | None:
    if isinstance(job.get("close_days_remaining"), int):
        return job["close_days_remaining"]
    closes = parse_date(job.get("source_closes_at"))
    return (closes - today_utc()).days if closes else None


def active_for_review(job: dict[str, Any], include_stale: bool = False) -> bool:
    return not job.get("is_closed_or_missing") and (include_stale or not job.get("is_stale"))


def broad_api_job(job: dict[str, Any]) -> bool:
    text = f"{job.get('source', '')} {job.get('attribution_note', '')}".lower()
    return any(provider in text for provider in ("adzuna", "jsearch", "serpapi", "remotive", "rapidapi"))


def unreviewed(job: dict[str, Any]) -> bool:
    return (job.get("review_status") or "unreviewed") == "unreviewed"


def review_queue(path: Path | str = DB_PATH, include_stale: bool = False, include_sample: bool = True) -> dict[str, list[dict[str, Any]]]:
    today = now_iso()
    rows = [job for job in list_jobs(path=path, include_sample=include_sample) if active_for_review(job, include_stale)]
    return {
        "new_today": [job for job in rows if unreviewed(job) and (job.get("first_seen_at") or job.get("date_found")) == today],
        "fresh_high_match": [job for job in rows if unreviewed(job) and int(job.get("match_score") or 0) >= 70 and not job.get("is_stale")],
        "closing_soon": [job for job in rows if (close_days(job) is not None and 0 <= close_days(job) <= 7) and job.get("status") not in {"applied", "skipped"}],
        "needs_review": [job for job in rows if unreviewed(job)],
        "packet_ready": [job for job in rows if job.get("status") in {"materials_generated", "ready_to_apply"}],
        "applied_follow_up": [job for job in rows if job.get("status") in {"applied", "follow_up_needed"} or job.get("review_status") == "applied"],
    }


def apply_today_reason(job: dict[str, Any]) -> str:
    days = close_days(job)
    if days is not None and 0 <= days <= 7:
        return f"Closing in {days} days"
    if int(job.get("match_score") or 0) >= 70:
        return job.get("score_band") or "Strong match score"
    if (job.get("posting_age_days") or 99) <= 14:
        return "Fresh posting"
    return "Worth reviewing"


def packet_status_for_job(job: dict[str, Any]) -> str:
    if job.get("applied_at") or job.get("status") == "applied" or job.get("outcome_status") == "applied":
        return "Applied"
    if job.get("status") == "ready_to_apply" or job.get("outcome_status") == "ready_to_apply":
        return "Ready to apply"
    if job.get("packet_qa_status") == "passed":
        return "Packet QA passed"
    if job.get("packet_qa_status") == "warnings":
        return "Packet QA warnings"
    if job.get("application_packet_files_json") or job.get("application_packet_dir") or job.get("packet_generated_at"):
        text = f"{job.get('generated_cover_letter', '')}\n{job.get('generated_followup_email', '')}"
        if "portfolio-gamma-six-p15gdz1e0v.vercel.app" in text and not re.search(r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b", text) and "expert" not in text.lower():
            return "Packet QA passed"
        return "Packet generated"
    return "Packet missing"


BLOCKER_RULES: list[tuple[str, str, str, str, list[str]]] = [
    ("work_authorization", "hard_blocker", "description", "Work authorization", ["authorized to work", "work authorization", "visa sponsorship", "visa sponsorship is not available", "no visa sponsorship"]),
    ("citizenship", "hard_blocker", "description", "Citizenship", ["u.s. citizen required", "us citizen required", "must be a u.s. citizen", "must be a us citizen", "u.s. citizenship required", "us citizenship required", "citizenship required"]),
    ("security_clearance", "review_needed", "description", "Security clearance", ["security clearance", "clearance", "public trust"]),
    ("transcript", "hard_blocker", "requirements", "Transcript", ["transcript required", "unofficial transcript", "official transcript", "academic transcript", "college transcript", "transcripts are required"]),
    ("degree_verification", "hard_blocker", "requirements", "Degree verification", ["degree verification", "education verification", "proof of degree"]),
    ("relocation", "review_needed", "description", "Relocation", ["relocation required", "must relocate", "relocate to", "relocation assistance"]),
    ("driver_license", "review_needed", "requirements", "Driver's license", ["driver's license", "drivers license", "driver license", "valid license"]),
    ("portfolio", "soft_warning", "requirements", "Portfolio", ["portfolio required", "portfolio", "work samples"]),
    ("references", "soft_warning", "requirements", "References", ["references required", "reference list", "references"]),
]


def evidence_for(text: str, phrase: str) -> str:
    match = re.search(re.escape(phrase), text, re.IGNORECASE)
    if not match:
        return ""
    start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start()))
    end_candidates = [index for index in [text.find(".", match.end()), text.find("\n", match.end())] if index != -1]
    end = min(end_candidates) if end_candidates else min(len(text), match.end() + 160)
    return text[start + 1:end + 1].strip()[:240]


def blocker_evidence(job: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {
        "title": str(job.get("title") or ""),
        "description": str(job.get("description") or ""),
        "requirements": str(job.get("requirements") or ""),
        "metadata": " ".join(str(job.get(key) or "") for key in ["work_authorization_note", "relocation_required", "language_requirement"]),
    }
    blockers: list[dict[str, Any]] = []
    for blocker_type, severity, preferred_field, label, phrases in BLOCKER_RULES:
        for source_field in [preferred_field, "requirements", "description", "metadata"]:
            text = fields.get(source_field, "")
            found = next((evidence_for(text, phrase) for phrase in phrases if evidence_for(text, phrase)), "")
            if found:
                actual_severity = "review_needed" if blocker_type == "transcript" and "may be submitted" in found.lower() else severity
                blockers.append({"blocker_type": blocker_type, "severity": actual_severity, "label": label, "evidence_text": found, "source_field": source_field, "resolved": False, "resolution_note": ""})
                break
    title = fields["title"]
    if senior := evidence_for(title, "senior") or evidence_for(title, "sr."):
        blockers.append({"blocker_type": "seniority", "severity": "review_needed", "label": "Seniority", "evidence_text": senior, "source_field": "title", "resolved": False, "resolution_note": ""})
    if senior := next((evidence_for(title, phrase) for phrase in ["principal", "director", "manager"] if evidence_for(title, phrase)), ""):
        blockers.append({"blocker_type": "seniority", "severity": "hard_blocker", "label": "Seniority", "evidence_text": senior, "source_field": "title", "resolved": False, "resolution_note": ""})
    return blockers


def resolved_blockers(job: dict[str, Any]) -> list[dict[str, Any]]:
    resolutions = job.get("blocker_resolutions_json") or {}
    blockers = []
    for blocker in blocker_evidence(job):
        resolution = resolutions.get(blocker["blocker_type"], {}) if isinstance(resolutions, dict) else {}
        blockers.append({
            **blocker,
            "resolved": bool(resolution.get("resolved") or resolution.get("not_applicable")),
            "not_applicable": bool(resolution.get("not_applicable")),
            "resolution_note": resolution.get("resolution_note", ""),
        })
    return blockers


def application_decision(job: dict[str, Any]) -> dict[str, Any]:
    score = int(job.get("match_score") or 0)
    packet_status = packet_status_for_job(job)
    link_ready = bool(job.get("apply_url") or job.get("source_url"))
    packet_ready = packet_status in {"Packet QA passed", "Packet QA warnings", "Ready to apply", "Applied"}
    blockers = resolved_blockers(job)
    unresolved = [blocker for blocker in blockers if not blocker["resolved"]]
    hard = [blocker for blocker in unresolved if blocker["severity"] == "hard_blocker"]
    review = [blocker for blocker in unresolved if blocker["severity"] == "review_needed"]
    soft = [blocker for blocker in unresolved if blocker["severity"] == "soft_warning"]
    blocker_labels = [blocker["label"] for blocker in [*hard, *review]]
    if not link_ready:
        blocker_labels.append("missing apply/source link")
    if not packet_ready:
        blocker_labels.append("packet not QA ready")
    manual_override = bool(job.get("manual_apply_override") and job.get("manual_apply_override_reason"))
    hard_seniority = any(blocker["blocker_type"] == "seniority" for blocker in hard)
    review_seniority = any(blocker["blocker_type"] == "seniority" for blocker in review)
    if score < 55 or hard_seniority:
        priority = "skip"
    elif score < 70 or review_seniority:
        priority = "maybe"
    elif manual_override and link_ready and packet_ready and not hard_seniority:
        priority = "apply_now"
    elif hard or review or not link_ready or not packet_ready:
        priority = "review_first"
    else:
        priority = "apply_now"
    next_action = {
        "apply_now": "Apply manually now.",
        "review_first": "Review blockers, then apply manually.",
        "maybe": "Review fit before spending packet time.",
        "skip": "Skip unless the posting is unusually compelling.",
    }[priority]
    reason = {
        "apply_now": "strong match, apply link available, packet QA passed",
        "review_first": "strong match but needs manual review",
        "maybe": "possible fit with fit or seniority concerns",
        "skip": "weak or likely mismatched role",
    }[priority]
    return {
        "application_priority": priority,
        "application_priority_reason": reason,
        "application_blockers": blocker_labels,
        "blockers": blockers,
        "soft_warnings": soft,
        "packet_ready": packet_ready,
        "link_ready": link_ready,
        "document_ready": not hard and not review,
        "next_action": next_action,
    }


def apply_today(path: Path | str = DB_PATH, limit: int = 5, include_stale: bool = False, include_sample: bool = True) -> list[dict[str, Any]]:
    excluded_statuses = {"applied", "skipped", "rejected"}
    excluded_outcomes = {"applied", "rejected", "closed", "withdrawn"}
    rows = [
        job
        for job in list_jobs(path=path, include_sample=include_sample)
        if job.get("status") not in excluded_statuses
        and job.get("outcome_status") not in excluded_outcomes
        and not job.get("is_closed_or_missing")
        and (include_stale or not job.get("is_stale"))
        and int(job.get("match_score") or 0) >= 55
        and not (broad_api_job(job) and not (job.get("apply_url") or job.get("source_url")))
    ]

    def rank(job: dict[str, Any]) -> tuple[Any, ...]:
        days = close_days(job)
        band = (job.get("score_band") or "").lower()
        strong_band = 0 if band in {"excellent fit", "strong fit"} or int(job.get("match_score") or 0) >= 70 else 1
        closing = days if days is not None and days >= 0 else 9999
        freshness = int(job.get("posting_age_days") if job.get("posting_age_days") is not None else 9999)
        confidence = 0 if job.get("freshness_confidence") == "source_posted_date" else 1
        first_seen = job.get("first_seen_at") or job.get("date_found") or ""
        first_seen_date = parse_date(first_seen)
        return (strong_band, -int(job.get("match_score") or 0), closing, freshness, confidence, -first_seen_date.toordinal() if first_seen_date else 0)

    selected = sorted(rows, key=rank)[: max(1, min(int(limit or 5), 25))]
    fields = {
        "id",
        "title",
        "company",
        "source",
        "location",
        "match_score",
        "score_band",
        "score_reason",
        "source_posted_at",
        "source_closes_at",
        "close_days_remaining",
        "freshness_bucket",
        "apply_url",
        "source_url",
        "original_source",
        "attribution_note",
        "link_status",
        "review_status",
        "application_submission_notes",
        "document_checklist",
        "packet_qa_status",
        "packet_qa_notes",
    }
    return [
        {
            **{key: job.get(key) for key in fields},
            "packet_status": packet_status_for_job(job),
            "recommendation_reason": apply_today_reason(job),
            **application_decision(job),
        }
        for job in selected
    ]


def review_counts(path: Path | str = DB_PATH, include_sample: bool = True) -> dict[str, int]:
    queue = review_queue(path, include_sample=include_sample)
    board = application_board(path, include_sample=include_sample)
    return {
        "unreviewed_jobs": len(queue["needs_review"]),
        "high_match_unreviewed_jobs": len(queue["fresh_high_match"]),
        "packets_ready": len(queue["packet_ready"]),
        "applied_followups_needed": len(board["follow_up_due"]),
        "follow_up_due_jobs": len(board["follow_up_due"]),
    }


def update_job_review(job_id: int, fields: dict[str, Any], path: Path | str = DB_PATH) -> dict[str, Any]:
    allowed = {"review_status", "review_notes", "priority_bucket"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unsupported review fields: {', '.join(sorted(bad))}")
    if "review_status" in updates:
        updates["reviewed_at"] = "" if updates["review_status"] == "unreviewed" else now_iso()
    return update_job_fields(job_id, updates, path)


def is_government_job(job: dict[str, Any]) -> bool:
    text = " ".join(str(job.get(key, "")) for key in ("source", "company", "title", "description")).lower()
    return any(word in text for word in ["usajobs", "government", "federal", "state", "county", "city of", "department", "agency", "naval"])


def default_follow_up_due(job: dict[str, Any], applied_at: str) -> str:
    applied = parse_date(applied_at) or today_utc()
    due = applied + timedelta(days=10 if is_government_job(job) else 7)
    closes = parse_date(job.get("source_closes_at"))
    return "" if closes and due > closes else due.isoformat()


def update_job_application(job_id: int, fields: dict[str, Any], path: Path | str = DB_PATH) -> dict[str, Any]:
    allowed = {
        "application_url_opened_at",
        "application_started_at",
        "applied_at",
        "follow_up_due_at",
        "follow_up_sent_at",
        "application_method",
        "application_contact_name",
        "application_contact_email",
        "application_confirmation_number",
        "application_submission_notes",
        "outcome_status",
    }
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unsupported application fields: {', '.join(sorted(bad))}")
    updates = {key: value for key, value in fields.items() if value is not None}
    return update_job_fields(job_id, updates, path)


def job_blockers(job_id: int, path: Path | str = DB_PATH) -> dict[str, Any]:
    job = get_job(job_id, path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    return {**application_decision(job), "job_id": job_id, "blocker_review_notes": job.get("blocker_review_notes", ""), "manual_apply_override": bool(job.get("manual_apply_override")), "manual_apply_override_reason": job.get("manual_apply_override_reason", "")}


def update_job_blockers(job_id: int, fields: dict[str, Any], path: Path | str = DB_PATH) -> dict[str, Any]:
    job = get_job(job_id, path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    updates: dict[str, Any] = {}
    resolutions = job.get("blocker_resolutions_json") or {}
    blocker_type = fields.get("blocker_type")
    if blocker_type:
        resolutions[blocker_type] = {
            **(resolutions.get(blocker_type, {}) if isinstance(resolutions, dict) else {}),
            **{key: fields[key] for key in ["resolved", "not_applicable", "resolution_note"] if key in fields},
        }
        updates["blocker_resolutions_json"] = resolutions
        updates["blocker_reviewed_at"] = now_iso()
    if "blocker_review_notes" in fields:
        updates["blocker_review_notes"] = fields["blocker_review_notes"]
    if "manual_apply_override" in fields:
        if fields["manual_apply_override"] and not fields.get("manual_apply_override_reason") and not job.get("manual_apply_override_reason"):
            raise ValueError("manual_apply_override_reason is required")
        updates["manual_apply_override"] = bool(fields["manual_apply_override"])
    if "manual_apply_override_reason" in fields:
        updates["manual_apply_override_reason"] = fields["manual_apply_override_reason"]
    if not updates:
        return job
    update_job_fields(job_id, updates, path)
    return job_blockers(job_id, path)


def mark_application_started(job_id: int, path: Path | str = DB_PATH) -> dict[str, Any]:
    today = now_iso()
    return update_job_application(job_id, {"application_started_at": today, "application_url_opened_at": today, "outcome_status": "ready_to_apply"}, path)


def mark_applied(job_id: int, path: Path | str = DB_PATH) -> dict[str, Any]:
    job = get_job(job_id, path)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    today = now_iso()
    updates = {
        "applied_at": today,
        "status": "applied",
        "outcome_status": "applied",
        "follow_up_due_at": job.get("follow_up_due_at") or default_follow_up_due(job, today),
    }
    if not job.get("application_started_at"):
        updates["application_started_at"] = today
    return update_job_fields(job_id, updates, path)


def mark_follow_up_sent(job_id: int, path: Path | str = DB_PATH) -> dict[str, Any]:
    return update_job_fields(job_id, {"follow_up_sent_at": now_iso(), "status": "applied", "outcome_status": "applied"}, path)


def follow_up_due(job: dict[str, Any]) -> bool:
    due = parse_date(job.get("follow_up_due_at"))
    return bool(due and due <= today_utc() and not job.get("follow_up_sent_at") and job.get("outcome_status") not in {"rejected", "closed", "withdrawn"})


def application_board(path: Path | str = DB_PATH, include_sample: bool = True) -> dict[str, list[dict[str, Any]]]:
    rows = list_jobs(path=path, include_sample=include_sample)
    active = [job for job in rows if not job.get("is_closed_or_missing")]
    return {
        "ready_to_apply": [job for job in active if (job.get("status") == "ready_to_apply" or job.get("outcome_status") == "ready_to_apply") and not job.get("application_started_at") and not job.get("applied_at")],
        "started": [job for job in active if job.get("application_started_at") and not job.get("applied_at")],
        "follow_up_due": [job for job in active if follow_up_due(job) or job.get("outcome_status") == "follow_up_due" or job.get("status") == "follow_up_needed"],
        "applied": [job for job in active if (job.get("applied_at") or job.get("status") == "applied" or job.get("outcome_status") == "applied") and not follow_up_due(job)],
        "interview": [job for job in rows if job.get("status") == "interview" or job.get("outcome_status") == "interview"],
        "rejected_closed": [job for job in rows if job.get("status") == "rejected" or job.get("outcome_status") in {"rejected", "closed", "withdrawn"} or job.get("is_closed_or_missing")],
    }


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
