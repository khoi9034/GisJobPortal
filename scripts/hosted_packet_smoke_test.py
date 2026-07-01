from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.reports import redact  # noqa: E402


def safe_print(text: str = "") -> None:
    print(redact(text).encode("ascii", errors="replace").decode("ascii"))


def request_json(base: str, path: str, method: str = "GET") -> Any:
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run hosted packet persistence smoke check.")
    parser.add_argument("--url", default="https://gisjobportal.onrender.com")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args(argv)
    jobs = request_json(args.url, "/review/apply-today")
    if not jobs:
        safe_print("No Apply Today jobs found.")
        return 1
    job = jobs[0]
    safe_print(f"selected: {job['id']} | {job['match_score']} | {job['title']} | {job.get('application_priority')}")
    if args.generate:
        generated = request_json(args.url, f"/jobs/{job['id']}/generate-application-packet", "POST")
        safe_print(f"generated packet qa: {generated.get('packet_qa_status')}")
    else:
        safe_print("dry run: pass --generate to create/update the hosted packet")
    packet = request_json(args.url, f"/jobs/{job['id']}/application-packet")
    files = packet.get("files") or {}
    safe_print(f"packet exists: {packet.get('exists')} | files: {len(files)} | qa: {packet.get('packet_qa_status') or 'not run'}")
    refreshed = request_json(args.url, "/review/apply-today")
    latest = next((row for row in refreshed if row["id"] == job["id"]), refreshed[0])
    safe_print(f"decision: {latest.get('application_priority')} | packet_status: {latest.get('packet_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
