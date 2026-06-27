from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.paths import BACKEND_ENV_PATH, SOURCES_PATH  # noqa: E402
from backend.app.source_validation import validate_source  # noqa: E402
from backend.app.sources import load_sources  # noqa: E402


def env_values(path: Path = BACKEND_ENV_PATH) -> dict[str, str]:
    values = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_set(value: str | None, placeholder: str = "") -> bool:
    return bool(value and not value.lower().startswith("replace_") and value != placeholder)


def usajobs_source(path: Path = SOURCES_PATH) -> dict:
    for source in load_sources(path):
        if source.get("name") == "USAJobs API":
            return source
    raise ValueError("USAJobs API source not found in config/sources.yaml")


def main(env_path: Path = BACKEND_ENV_PATH, sources_path: Path = SOURCES_PATH) -> int:
    values = env_values(env_path)
    user_agent_ok = is_set(values.get("USAJOBS_USER_AGENT"), "your_email@example.com")
    key_ok = is_set(values.get("USAJOBS_AUTHORIZATION_KEY"))
    source = usajobs_source(sources_path)

    print(f"backend/.env exists: {'yes' if env_path.exists() else 'no'}")
    print(f"USAJOBS_USER_AGENT set: {'yes' if user_agent_ok else 'no'}")
    print(f"USAJOBS_AUTHORIZATION_KEY set: {'yes' if key_ok else 'no'}")
    print(f"USAJobs source enabled: {'yes' if source.get('enabled') else 'no'}")
    print("USAJobs freshness: posted date + close date supported")

    if not user_agent_ok or not key_ok:
        print("Missing USAJobs credentials.")
        print("Safe local steps:")
        print("1. Create backend/.env if it does not exist.")
        print("2. Add USAJOBS_USER_AGENT=your_email@example.com")
        print("3. Add USAJOBS_AUTHORIZATION_KEY=replace_with_your_local_secret")
        print('4. Run python scripts/source_toggle.py enable "USAJobs API"')
        print("5. Run python scripts/validate_sources.py")
        print("6. Run python scripts/refresh_jobs.py")
        print("Do not commit backend/.env.")
        return 1

    os.environ["USAJOBS_USER_AGENT"] = values["USAJOBS_USER_AGENT"]
    os.environ["USAJOBS_AUTHORIZATION_KEY"] = values["USAJOBS_AUTHORIZATION_KEY"]
    result = validate_source(source)
    print(f"Validation status: {result['validation_status']}")
    print(f"Reachable endpoint: {'yes' if result['reachable_endpoint'] else 'no'}")
    print(f"Jobs sampled: {result['jobs_sampled']}")
    if result["last_error"]:
        print(f"Error: {result['last_error']}")
    return 0 if result["validation_status"] in {"ok", "warning", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
