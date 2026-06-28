from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.paths import GENERATED_DIR, PRIVATE_DIR, RUNTIME_DIR  # noqa: E402

EXPORT_DIR = RUNTIME_DIR / "exports"
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")
SKIP_JOB_FIELDS = {
    "application_packet_dir",
    "generated_cover_letter",
    "generated_followup_email",
    "recruiter_message",
    "resume_bullet_suggestions",
}


def redact(text: str) -> str:
    for path in (PRIVATE_DIR, GENERATED_DIR):
        text = text.replace(str(path), "[local-path]")
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            text = text.replace(secret, "[redacted]")
    return text


def safe_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in SKIP_JOB_FIELDS}


def export_db(output_dir: Path = EXPORT_DIR, db_path: Path | str = db.DB_PATH) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "jobs": [safe_job(job) for job in db.list_jobs(path=db_path)],
        "sources": db.list_sources(path=db_path),
    }
    output = output_dir / f"db_seed_{datetime.now(UTC):%Y%m%d}.json"
    output.write_text(redact(json.dumps(payload, indent=2, ensure_ascii=True)), encoding="utf-8")
    return output


def main() -> int:
    output = export_db()
    print(f"exported seed data: {output}")
    print("note: runtime/exports is ignored by Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
