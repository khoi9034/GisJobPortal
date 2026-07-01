from __future__ import annotations

import argparse
import json
from typing import Any
from urllib import error, request


DEFAULT_URL = "https://gisjobportal.onrender.com"
PATHS = (
    "/dashboard/summary",
    "/deployment/status",
    "/jobs",
    "/sources",
    "/stats/overview",
    "/review/queue",
    "/application/board",
    "/reports/latest",
)


def fetch_json(base_url: str, path: str) -> Any:
    with request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def count_grouped(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(rows) for rows in value.values() if isinstance(rows, list))
    return 0


def collect(base_url: str) -> tuple[dict[str, Any], dict[str, str]]:
    rows: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for path in PATHS:
        try:
            rows[path] = fetch_json(base_url, path)
        except (OSError, TimeoutError, error.URLError, ValueError, json.JSONDecodeError) as exc:
            errors[path] = f"{type(exc).__name__}: {exc}"
    return rows, errors


def summarize(rows: dict[str, Any], errors: dict[str, str]) -> dict[str, Any]:
    dashboard = rows.get("/dashboard/summary") or {}
    status = rows.get("/deployment/status") or {}
    jobs = rows.get("/jobs") or []
    sources = rows.get("/sources") or []
    stats = rows.get("/stats/overview") or {}
    queue = rows.get("/review/queue") or {}
    board = rows.get("/application/board") or {}
    report = rows.get("/reports/latest") or {}
    warnings = []
    if dashboard.get("job_count") not in (None, len(jobs)) and "/jobs" not in errors:
        warnings.append(f"dashboard/summary job_count={dashboard.get('job_count')} but /jobs length={len(jobs)}")
    if dashboard.get("source_count") not in (None, len(sources)) and "/sources" not in errors:
        warnings.append(f"dashboard/summary source_count={dashboard.get('source_count')} but /sources length={len(sources)}")
    if dashboard.get("job_count", 0) > 0 and "/jobs" in errors:
        warnings.append("dashboard/summary has jobs but /jobs failed; frontend should show summary top jobs")
    if status.get("job_count") not in (None, len(jobs)):
        warnings.append(f"deployment/status job_count={status.get('job_count')} but /jobs length={len(jobs)}")
    if status.get("source_count") not in (None, len(sources)):
        warnings.append(f"deployment/status source_count={status.get('source_count')} but /sources length={len(sources)}")
    if jobs and count_grouped(queue) == 0:
        warnings.append("/jobs has rows but /review/queue is empty")
    if jobs and stats.get("total") in (0, None):
        warnings.append("/jobs has rows but /stats/overview total is empty")
    if errors:
        warnings.append("one or more endpoints failed; frontend should show partial data plus an error")
    return {
        "deployment_job_count": status.get("job_count", 0),
        "summary_job_count": dashboard.get("job_count", 0),
        "summary_top_jobs": len(dashboard.get("top_jobs") or []),
        "jobs_count": len(jobs),
        "deployment_source_count": status.get("source_count", 0),
        "summary_source_count": dashboard.get("source_count", 0),
        "sources_count": len(sources),
        "stats_total": stats.get("total", 0),
        "review_queue_counts": {key: len(value) for key, value in queue.items() if isinstance(value, list)},
        "application_board_counts": {key: len(value) for key, value in board.items() if isinstance(value, list)},
        "latest_report_exists": bool(report.get("exists")),
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether the live frontend API has visible data.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Hosted backend URL")
    args = parser.parse_args(argv)
    rows, errors = collect(args.url)
    summary = summarize(rows, errors)
    print(f"backend URL: {args.url.rstrip('/')}")
    print(f"dashboard summary jobs: {summary['summary_job_count']} top jobs: {summary['summary_top_jobs']}")
    print(f"jobs: {summary['jobs_count']} (/deployment/status: {summary['deployment_job_count']})")
    print(f"sources: {summary['sources_count']} (/dashboard/summary: {summary['summary_source_count']}, /deployment/status: {summary['deployment_source_count']})")
    print(f"stats total: {summary['stats_total']}")
    print(f"review queue: {summary['review_queue_counts']}")
    print(f"application board: {summary['application_board_counts']}")
    print(f"latest report exists: {summary['latest_report_exists']}")
    for path, message in errors.items():
        print(f"error {path}: {message}")
    for warning in summary["warnings"]:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
