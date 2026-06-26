from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "jobs.sqlite3"
PROFILE_PATH = CONFIG_DIR / "profile.yaml"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
SAMPLE_JOBS_PATH = DATA_DIR / "sample_jobs.json"

