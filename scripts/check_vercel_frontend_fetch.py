from __future__ import annotations

import argparse
import json
import re
from typing import Any
from urllib import error, request


DEFAULT_SITE = "https://gis-job-portal.vercel.app"
DEFAULT_API = "https://gisjobportal.onrender.com"
PATHS = (
    "/health",
    "/deployment/status",
    "/jobs",
    "/sources",
    "/stats/overview",
    "/review/queue",
    "/reports/latest",
)


def fetch_text(url: str) -> str:
    with request.urlopen(url, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str, origin: str) -> tuple[Any, dict[str, str], int]:
    req = request.Request(url, headers={"Origin": origin})
    with request.urlopen(req, timeout=60) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return json.loads(response.read().decode("utf-8")), headers, response.status


def preflight(url: str, origin: str) -> tuple[dict[str, str], int]:
    req = request.Request(
        url,
        method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    with request.urlopen(req, timeout=45) as response:
        return {key.lower(): value for key, value in response.headers.items()}, response.status


def count_grouped(value: Any) -> dict[str, int]:
    return {key: len(rows) for key, rows in value.items() if isinstance(rows, list)} if isinstance(value, dict) else {}


def js_assets(html: str) -> list[str]:
    return sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))


def asset_url(site_url: str, src: str) -> str:
    return src if src.startswith("http") else f"{site_url.rstrip('/')}{src}"


def bundle_mentions_api(site_url: str, html: str, api_url: str) -> bool:
    for src in js_assets(html):
        try:
            if api_url in fetch_text(asset_url(site_url, src)):
                return True
        except OSError:
            continue
    return False


def safe_error(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        return f"HTTP {exc.code}"
    return f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check browser-origin Vercel frontend API fetch behavior.")
    parser.add_argument("--site", default=DEFAULT_SITE)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args(argv)
    site = args.site.rstrip("/")
    api = args.api.rstrip("/")
    warnings: list[str] = []
    errors: list[str] = []

    html = fetch_text(site)
    print(f"site: {site}")
    print(f"api: {api}")
    print(f"html bytes: {len(html)}")
    print(f"html mode badge: {'Live API' if 'Live API' in html else 'not found'}")
    print(f"html initial shell: {'empty/loading' if 'No jobs in this view yet.' in html or 'Loading live jobs...' in html else 'data'}")
    print(f"bundle has api url: {bundle_mentions_api(site, html, api)}")

    rows: dict[str, Any] = {}
    for path in PATHS:
        url = f"{api}{path}"
        try:
            options_headers, options_status = preflight(url, site)
            data, headers, status = fetch_json(url, site)
            rows[path] = data
            cors_origin = headers.get("access-control-allow-origin", "")
            preflight_origin = options_headers.get("access-control-allow-origin", "")
            if status != 200 or options_status != 200:
                errors.append(f"{path}: bad status get={status} options={options_status}")
            if cors_origin != site or preflight_origin != site:
                errors.append(f"{path}: CORS origin mismatch")
        except Exception as exc:
            errors.append(f"{path}: {safe_error(exc)}")

    status = rows.get("/deployment/status") or {}
    jobs = rows.get("/jobs") or []
    sources = rows.get("/sources") or []
    stats = rows.get("/stats/overview") or {}
    queue = rows.get("/review/queue") or {}
    report = rows.get("/reports/latest") or {}

    if not isinstance(jobs, list):
        errors.append("/jobs did not return a list")
        jobs = []
    if not isinstance(sources, list):
        errors.append("/sources did not return a list")
        sources = []
    if not isinstance(queue, dict):
        errors.append("/review/queue did not return an object")
        queue = {}
    if not isinstance(report, dict):
        errors.append("/reports/latest did not return an object")
        report = {}
    if status.get("job_count") not in (None, len(jobs)):
        warnings.append(f"deployment/status job_count={status.get('job_count')} but /jobs length={len(jobs)}")
    if status.get("source_count") not in (None, len(sources)):
        warnings.append(f"deployment/status source_count={status.get('source_count')} but /sources length={len(sources)}")
    if len(jobs) and not (stats.get("total") or 0):
        warnings.append("/jobs has rows but /stats/overview total is empty")
    if len(jobs) and not sum(count_grouped(queue).values()):
        warnings.append("/jobs has rows but /review/queue is empty")

    print(f"deployment/status jobs: {status.get('job_count', 0)}")
    print(f"/jobs length: {len(jobs)}")
    print(f"/sources length: {len(sources)}")
    print(f"/stats/overview total: {stats.get('total', 0)}")
    print(f"/review/queue counts: {count_grouped(queue)}")
    print(f"/reports/latest exists: {bool(report.get('exists'))}")
    for warning in warnings:
        print(f"warning: {warning}")
    for item in errors:
        print(f"error: {item}")
    if not errors and "No jobs in this view yet." in html and len(jobs):
        print("note: prerendered HTML is an empty shell; hydrated browser data should replace it.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
