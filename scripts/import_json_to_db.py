from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402


def import_file(file_path: Path, db_path: Path | str = db.DB_PATH) -> dict[str, int]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    inserted = 0
    duplicates = 0
    sources = 0
    for source in payload.get("sources", []):
        if isinstance(source, dict) and source.get("name"):
            db.upsert_source(source, db_path)
            sources += 1
    for job in payload.get("jobs", []):
        if not isinstance(job, dict):
            continue
        _, duplicate = db.insert_job({key: value for key, value in job.items() if key in db.JOB_COLUMNS}, db_path)
        if duplicate:
            duplicates += 1
        else:
            inserted += 1
    return {"sources": sources, "inserted": inserted, "duplicates": duplicates}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a db_seed_YYYYMMDD.json file into the configured database.")
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)
    result = import_file(args.file)
    print(f"imported sources: {result['sources']}")
    print(f"inserted jobs: {result['inserted']}")
    print(f"duplicates preserved: {result['duplicates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
