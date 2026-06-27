import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
PRIVATE_DIR = ROOT / "private"
GENERATED_DIR = ROOT / "generated"
BACKEND_ENV_PATH = ROOT / "backend" / ".env"
PROFILE_PATH = CONFIG_DIR / "profile.yaml"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
SEARCH_PROFILES_PATH = CONFIG_DIR / "search_profiles.yaml"
APPLICATION_RULES_PATH = CONFIG_DIR / "application_rules.yaml"
SAMPLE_JOBS_PATH = DATA_DIR / "sample_jobs.json"
RESUME_DIR = PRIVATE_DIR / "resume"
TRANSCRIPT_DIR = PRIVATE_DIR / "transcript"
RESUME_EXTRACTED_PATH = RESUME_DIR / "resume_extracted.md"
TRANSCRIPT_SUMMARY_PATH = TRANSCRIPT_DIR / "transcript_summary.md"
APPLICATION_PACKETS_DIR = GENERATED_DIR / "application_packets"


def load_backend_env(path: Path = BACKEND_ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_path(strict: bool = True) -> Path:
    load_backend_env()
    url = os.getenv("DATABASE_URL", "sqlite:///./data/jobs.sqlite3")
    if url.startswith("sqlite:///"):
        raw_path = url.removeprefix("sqlite:///")
        path = Path(raw_path)
        return path if path.is_absolute() else ROOT / path
    # ponytail: keep DB layer sqlite-only until Postgres is actually hosted.
    if not strict:
        return DATA_DIR / "jobs.sqlite3"
    raise ValueError("Only sqlite:/// DATABASE_URL is supported locally; add a Postgres driver when production storage exists.")


def api_env() -> str:
    load_backend_env()
    return os.getenv("API_ENV", "local")


def cors_origins() -> list[str]:
    load_backend_env()
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,https://gis-job-portal.vercel.app")
    raw = raw.strip().strip("[]")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:3000", "https://gis-job-portal.vercel.app"]


DB_PATH = database_path(strict=False)
