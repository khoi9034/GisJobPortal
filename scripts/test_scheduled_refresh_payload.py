from __future__ import annotations

import argparse
import json
from typing import Any
from urllib import request


DEFAULT_URL = "https://gisjobportal.onrender.com"


def fetch_json(base_url: str, path: str) -> Any:
    with request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run the scheduled hosted refresh setup without sending the admin token.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Hosted backend URL")
    args = parser.parse_args(argv)
    base_url = args.url.rstrip("/")

    status = fetch_json(base_url, "/deployment/status")
    report = fetch_json(base_url, "/reports/latest")

    print(f"backend URL: {base_url}")
    print("GitHub Action will call: POST /admin/refresh-jobs")
    print("GitHub Action will send: X-Admin-Refresh-Token from secrets.ADMIN_REFRESH_TOKEN")
    print(f"api_env: {status.get('api_env')}")
    print(f"database_runtime_type: {status.get('database_runtime_type')}")
    print(f"production_ready: {status.get('production_ready')}")
    print(f"job_count: {status.get('job_count')}")
    print(f"real_sources_enabled: {status.get('real_sources_enabled')}")
    print(f"latest_report_exists: {bool(report.get('exists'))}")
    print(f"latest_report_date: {report.get('date') or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
