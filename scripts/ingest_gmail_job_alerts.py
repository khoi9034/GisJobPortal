from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.email_alerts import gmail_config, gmail_configured, ingest_gmail_alerts, parse_alert_jobs  # noqa: E402
from backend.app.profile import load_profile  # noqa: E402
from backend.app.scoring import score_job  # noqa: E402


def configured(config: dict[str, str]) -> bool:
    return gmail_configured(config)


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

    result = ingest_gmail_alerts()
    print(f"gmail configured: {'yes' if result['gmail_configured'] else 'no'}")
    print(f"alert emails checked: {result['alert_emails_checked']}")
    print(f"alert emails parsed: {result['alert_emails_parsed']}")
    print(f"alert jobs inserted: {result['alert_jobs_inserted']}")
    print(f"alert duplicates updated: {result['alert_duplicates_updated']}")
    print(f"alert parse errors: {result['alert_parse_errors']}")
    print(f"gmail errors: {len(result['gmail_errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
