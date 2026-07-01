from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib import error, request


DEFAULT_URL = "https://gisjobportal.onrender.com"
PATHS = (
    "/dashboard/summary",
    "/jobs",
    "/stats/overview",
    "/review/apply-today",
    "/application/board",
    "/sources",
    "/reports/latest",
)


def fetch_endpoint(base_url: str, path: str, timeout: int = 30) -> tuple[int | None, float, Any | None, str | None]:
    started = time.perf_counter()
    try:
        with request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=timeout) as response:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return response.status, elapsed_ms, json.loads(response.read().decode("utf-8")), None
    except error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return exc.code, elapsed_ms, None, f"HTTPError: {exc.reason}"
    except (OSError, TimeoutError, error.URLError, ValueError, json.JSONDecodeError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return None, elapsed_ms, None, f"{type(exc).__name__}: {exc}"


def group_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(rows) for rows in value.values() if isinstance(rows, list))
    return 0


def summarize(path: str, payload: Any) -> str:
    if payload is None:
        return "no payload"
    if isinstance(payload, list):
        return f"items={len(payload)}"
    if not isinstance(payload, dict):
        return type(payload).__name__
    if path == "/dashboard/summary":
        return f"jobs={payload.get('job_count', 0)} sources={payload.get('source_count', 0)} top_jobs={len(payload.get('top_jobs') or [])} digest={bool((payload.get('digest') or {}).get('exists'))}"
    if path == "/stats/overview":
        return f"total={payload.get('total', 0)} high={payload.get('high_matches', 0)}"
    if path in {"/application/board", "/review/queue"}:
        return f"grouped_items={group_count(payload)}"
    if path == "/reports/latest":
        return f"exists={bool(payload.get('exists'))} summary_keys={len(payload.get('summary') or {})}"
    return f"keys={len(payload)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time live dashboard endpoints without printing secrets.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Hosted backend URL")
    args = parser.parse_args(argv)
    print(f"backend URL: {args.url.rstrip('/')}")
    for path in PATHS:
        status, elapsed_ms, payload, failure = fetch_endpoint(args.url, path)
        status_text = str(status) if status is not None else "failed"
        summary = summarize(path, payload)
        suffix = f" error={failure}" if failure else ""
        print(f"{path}: status={status_text} time_ms={elapsed_ms:.0f} {summary}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
