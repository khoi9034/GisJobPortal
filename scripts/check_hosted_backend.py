from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib import error, request

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")


def redact(value: Any) -> str:
    text = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            text = text.replace(secret, "[redacted]")
    return text


def fetch_json(base_url: str, path: str) -> Any:
    with request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def count_rows(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(rows) for rows in value.values() if isinstance(rows, list))
    return 0


def check_backend(base_url: str) -> dict[str, Any]:
    health = fetch_json(base_url, "/health")
    status = fetch_json(base_url, "/deployment/status")
    jobs = fetch_json(base_url, "/jobs")
    queue = fetch_json(base_url, "/review/queue")
    board = fetch_json(base_url, "/application/board")
    real_jobs = [job for job in jobs if isinstance(job, dict) and job.get("source") not in {"Demo", "Sample GIS Jobs"}]
    runtime_type = status.get("database_runtime_type") or status.get("database_type", "unknown")
    blockers = list(status.get("production_blockers") or [])
    if health.get("status") != "ok":
        blockers.append("health is not ok")
    if status.get("api_env") != "production":
        blockers.append("API_ENV is not production")
    if runtime_type != "postgres":
        blockers.append("database runtime is not postgres")
    if int(status.get("real_sources_enabled") or 0) <= 0:
        blockers.append("no real sources enabled")
    if not real_jobs:
        blockers.append("no real jobs returned")
    production_ready = not blockers
    return {
        "health": health.get("status", "unknown"),
        "api_env": status.get("api_env", "unknown"),
        "database_url_present": status.get("database_url_present", "unknown"),
        "database_url_scheme": status.get("database_url_scheme", "unknown"),
        "database_runtime_type": runtime_type,
        "database_type": runtime_type,
        "configured_database_type": status.get("configured_database_type", "unknown"),
        "job_count": len(jobs),
        "real_job_count": len(real_jobs),
        "real_sources_enabled": int(status.get("real_sources_enabled") or 0),
        "review_queue_jobs": count_rows(queue),
        "application_board_jobs": count_rows(board),
        "production_blockers": sorted(set(blockers)),
        "production_ready": production_ready,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check a hosted GisJobPortal backend.")
    parser.add_argument("--url", required=True, help="Hosted backend base URL, for example https://gis-api.example.com")
    args = parser.parse_args(argv)
    try:
        result = check_backend(args.url)
    except (OSError, error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"hosted backend check failed: {redact(exc)}")
        return 1
    print(f"backend URL: {redact(args.url.rstrip('/'))}")
    print(f"status: {result['health']}")
    print(f"api env: {result['api_env']}")
    print(f"database_url_present: {result['database_url_present']}")
    print(f"database_url_scheme: {result['database_url_scheme']}")
    print(f"database_runtime_type: {result['database_runtime_type']}")
    print(f"configured database type: {result['configured_database_type']}")
    print(f"job count: {result['job_count']}")
    print(f"real job count: {result['real_job_count']}")
    print(f"real sources enabled: {result['real_sources_enabled']}")
    print(f"review queue jobs: {result['review_queue_jobs']}")
    print(f"application board jobs: {result['application_board_jobs']}")
    print(f"production blockers: {', '.join(result['production_blockers']) if result['production_blockers'] else 'none'}")
    print(f"production ready: {'yes' if result['production_ready'] else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
