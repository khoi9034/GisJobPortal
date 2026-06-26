from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
PRIVATE_DIR = ROOT / "private"
GENERATED_DIR = ROOT / "generated"
DB_PATH = DATA_DIR / "jobs.sqlite3"
PROFILE_PATH = CONFIG_DIR / "profile.yaml"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
APPLICATION_RULES_PATH = CONFIG_DIR / "application_rules.yaml"
SAMPLE_JOBS_PATH = DATA_DIR / "sample_jobs.json"
RESUME_DIR = PRIVATE_DIR / "resume"
TRANSCRIPT_DIR = PRIVATE_DIR / "transcript"
RESUME_EXTRACTED_PATH = RESUME_DIR / "resume_extracted.md"
TRANSCRIPT_SUMMARY_PATH = TRANSCRIPT_DIR / "transcript_summary.md"
APPLICATION_PACKETS_DIR = GENERATED_DIR / "application_packets"
