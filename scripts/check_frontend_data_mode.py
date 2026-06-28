from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ENV_LOCAL = ROOT / "frontend" / ".env.local"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")


def redact(value: Any) -> str:
    text = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            text = text.replace(secret, "[redacted]")
    return text


def read_env_file(path: Path = FRONTEND_ENV_LOCAL) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def frontend_env(path: Path = FRONTEND_ENV_LOCAL) -> dict[str, str]:
    local = read_env_file(path)
    mode = local.get("NEXT_PUBLIC_API_MODE") or os.getenv("NEXT_PUBLIC_API_MODE") or "demo"
    base = local.get("NEXT_PUBLIC_API_BASE_URL") or local.get("NEXT_PUBLIC_API_URL") or os.getenv("NEXT_PUBLIC_API_BASE_URL") or os.getenv("NEXT_PUBLIC_API_URL") or ""
    return {"mode": mode, "base_url": base}


def fetch_json(url: str) -> Any:
    with request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main(env_path: Path = FRONTEND_ENV_LOCAL) -> int:
    env = frontend_env(env_path)
    check_base = env["base_url"] or DEFAULT_BACKEND_URL
    print(f"frontend env file: {env_path if env_path.exists() else 'not found'}")
    print(f"frontend API mode: {redact(env['mode'])}")
    print(f"frontend API base URL: {redact(env['base_url'] or '(missing; checking http://127.0.0.1:8000)')}")
    if env["mode"] == "local" and not env["base_url"]:
        print("warning: Local API mode is enabled but NEXT_PUBLIC_API_BASE_URL is missing.")
    try:
        health = fetch_json(f"{check_base.rstrip('/')}/health")
        jobs = fetch_json(f"{check_base.rstrip('/')}/jobs")
    except (OSError, error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"backend check: failed - {redact(exc)}")
        return 1

    real_jobs = [job for job in jobs if job.get("source") not in {"Demo", "Sample GIS Jobs"}]
    print(f"backend /health: {health.get('status')} ({health.get('database')})")
    print(f"backend /jobs count: {len(jobs)}")
    print(f"real backend jobs: {len(real_jobs)}")
    if env["mode"] == "demo" and real_jobs:
        print("warning: frontend is in demo mode while the backend has real jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
