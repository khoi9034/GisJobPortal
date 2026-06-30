from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.email_alerts import parse_alert_jobs  # noqa: E402
from backend.app.paths import load_backend_env  # noqa: E402
from backend.app.profile import load_profile  # noqa: E402
from backend.app.scoring import score_job  # noqa: E402


def gmail_config() -> dict[str, str]:
    load_backend_env()
    return {
        "enabled": os.getenv("GMAIL_INGESTION_ENABLED", "false").lower(),
        "client_id": os.getenv("GMAIL_CLIENT_ID", ""),
        "client_secret": os.getenv("GMAIL_CLIENT_SECRET", ""),
        "token_path": os.getenv("GMAIL_TOKEN_PATH", "runtime/secrets/gmail_token.local.json"),
        "query": os.getenv("GMAIL_ALERT_QUERY", "(from:linkedin.com OR from:indeed.com) newer_than:14d"),
    }


def configured(config: dict[str, str]) -> bool:
    token_path = ROOT / config["token_path"]
    return (
        config["enabled"] == "true"
        and bool(config["client_id"])
        and not config["client_id"].lower().startswith("replace_")
        and bool(config["client_secret"])
        and not config["client_secret"].lower().startswith("replace_")
        and token_path.exists()
    )


def import_text(source_hint: str, raw_text: str, db_path: Path | str = db.DB_PATH) -> dict[str, int]:
    profile = load_profile()
    inserted = duplicates = 0
    for job in parse_alert_jobs(source_hint, raw_text):
        scored = {**job, **score_job(job, profile)}
        _, duplicate = db.insert_job(scored, db_path)
        duplicates += int(duplicate)
        inserted += int(not duplicate)
    return {"alert_jobs_inserted": inserted, "alert_duplicates_updated": duplicates}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest authorized Gmail job alert emails.")
    parser.add_argument("--source-hint", choices=["linkedin", "indeed"], default="")
    parser.add_argument("--text-file", default="")
    args = parser.parse_args(argv)

    if args.text_file:
        raw = Path(args.text_file).read_text(encoding="utf-8")
        result = import_text(args.source_hint or "linkedin", raw)
        print(f"alert jobs inserted: {result['alert_jobs_inserted']}")
        print(f"alert duplicates updated: {result['alert_duplicates_updated']}")
        return 0

    config = gmail_config()
    if not configured(config):
        print("Gmail job alert ingestion is not configured.")
        print("Add local OAuth values to backend/.env and keep the token under runtime/secrets/.")
        print(f"Query to use later: {config['query']}")
        return 0

    # ponytail: Gmail API hookup is intentionally deferred until OAuth tokens exist.
    print("Gmail credentials found, but live Gmail fetch is not enabled in this safe skeleton yet.")
    print("Use --text-file for parser testing, or wire Gmail API after OAuth setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
