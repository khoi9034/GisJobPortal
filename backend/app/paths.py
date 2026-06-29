import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
PRIVATE_DIR = ROOT / "private"
GENERATED_DIR = ROOT / "generated"
RUNTIME_DIR = ROOT / "runtime"
REPORTS_DIR = RUNTIME_DIR / "reports"
LOGS_DIR = RUNTIME_DIR / "logs"
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
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    local_file = values.get("API_ENV") == "local"
    for key, value in values.items():
        if local_file or key not in os.environ:
            os.environ[key] = value


def database_url() -> str:
    load_backend_env()
    return os.getenv("DATABASE_URL", "sqlite:///./data/jobs.sqlite3")


def database_url_present() -> bool:
    load_backend_env()
    return bool(os.getenv("DATABASE_URL", "").strip())


def database_url_scheme(url: str | None = None) -> str:
    value = url or database_url()
    return value.split(":", 1)[0] if ":" in value else "unknown"


def database_type(url: str | None = None) -> str:
    value = (url or database_url()).lower()
    if value.startswith("sqlite"):
        return "sqlite"
    if value.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        return "postgres"
    return "unknown"


def database_runtime_type() -> str:
    return database_type()


def postgres_connection_url() -> str:
    url = database_url()
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def database_path(strict: bool = True) -> Path:
    url = database_url()
    if database_type(url) == "sqlite" and url.startswith("sqlite:///"):
        raw_path = url.removeprefix("sqlite:///")
        path = Path(raw_path)
        return path if path.is_absolute() else ROOT / path
    # ponytail: the sqlite3 DB layer stays local-only until the hosted Postgres cutover.
    if not strict:
        return DATA_DIR / "jobs.sqlite3"
    raise ValueError("DATABASE_URL is not a sqlite:/// URL; use hosted Postgres only after the DB adapter cutover.")


def api_env() -> str:
    load_backend_env()
    return os.getenv("API_ENV", "local")


def admin_refresh_token() -> str:
    load_backend_env()
    return os.getenv("ADMIN_REFRESH_TOKEN", "").strip()


def cors_origins() -> list[str]:
    load_backend_env()
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,https://gis-job-portal.vercel.app")
    raw = raw.strip().strip("[]")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:3000", "https://gis-job-portal.vercel.app"]


DB_PATH = database_path(strict=False)
