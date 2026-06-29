from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "runtime" / "secrets" / "admin_refresh_token.local.txt"
REFRESH_TIMEOUT_SECONDS = 600


def admin_refresh(base_url: str, token: str) -> dict:
    req = request.Request(
        f"{base_url.rstrip('/')}/admin/refresh-jobs",
        data=b"{}",
        headers={"Content-Type": "application/json", "X-Admin-Refresh-Token": token},
        method="POST",
    )
    with request.urlopen(req, timeout=REFRESH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def load_token(path: Path | None = None) -> str:
    path = path or TOKEN_PATH
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return getpass.getpass("ADMIN_REFRESH_TOKEN: ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the hosted admin job refresh.")
    parser.add_argument("--url", default="https://gisjobportal.onrender.com", help="Backend URL")
    args = parser.parse_args(argv)
    token = load_token()
    try:
        result = admin_refresh(args.url, token)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"refresh failed: HTTP {exc.code} {body}")
        return 1
    finally:
        token = ""
    print("admin refresh summary")
    for key in ["sources_checked", "jobs_collected", "inserted", "duplicates_updated", "stale_jobs", "strong_excellent_matches", "report_generated"]:
        print(f"- {key}: {result.get(key)}")
    errors = result.get("source_errors") or {}
    print(f"- source_errors: {len(errors)}")
    for source, message in errors.items():
        print(f"  - {source}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
