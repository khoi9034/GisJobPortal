from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402
from backend.app.sources import load_sources  # noqa: E402

TARGETS_PATH = ROOT / "docs" / "LIVE_SOURCE_TARGETS.md"
DISCOVERY_REPORT_PATH = ROOT / "docs" / "SOURCE_DISCOVERY_REPORT.md"
ACTIVATION_STATUS_PATH = ROOT / "docs" / "SOURCE_ACTIVATION_STATUS.md"
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")

UNSUPPORTED_SIGNALS = [
    "myworkdayjobs.com",
    "workdayjobs.com",
    "workday.com",
    "linkedin.com/jobs",
    "indeed.com",
    "taleo.net",
    "successfactors.com",
    "oraclecloud.com",
    "icims.com",
    "smartrecruiters.com",
    "paycomonline.net",
    "paylocity.com",
    "ultipro.com",
]


def redact(value: Any) -> str:
    text = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in SECRET_WORDS) and secret and len(secret) > 4:
            text = text.replace(secret, "[redacted]")
    return text


def read_targets(path: Path = TARGETS_PATH) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "Organization" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 7:
            rows.append(
                {
                    "organization": cells[0],
                    "expected_type": cells[1],
                    "status": cells[2],
                    "url": cells[3],
                    "notes": cells[4],
                    "priority": cells[5],
                    "date_support": cells[6],
                }
            )
    return rows


def fetch_url(url: str, timeout: int = 12) -> tuple[str, str, str]:
    req = request.Request(url, headers={"User-Agent": "GIS Apply Copilot source discovery"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read(400_000).decode("utf-8", errors="replace")
            return response.geturl(), body, ""
    except (error.URLError, TimeoutError, ValueError) as exc:
        return url, "", redact(str(exc))


def _match(pattern: str, text: str) -> str:
    found = re.search(pattern, text, flags=re.IGNORECASE)
    return found.group(1).strip("/") if found else ""


def classify_url(url: str, html: str = "", final_url: str = "") -> dict[str, str]:
    text = f"{url}\n{final_url}\n{html}"
    lower = text.lower()
    greenhouse_token = (
        _match(r"boards\.greenhouse\.io/([a-z0-9_-]+)", text)
        or _match(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", text)
        or _match(r"greenhouse\.io/embed/job_board\?for=([a-z0-9_-]+)", text)
    )
    if greenhouse_token:
        return {"type": "greenhouse", "status": "confirmed", "detail": f"board_token={greenhouse_token}"}
    lever_site = _match(r"jobs\.lever\.co/([a-z0-9_-]+)", text) or _match(r"api\.lever\.co/v0/postings/([a-z0-9_-]+)", text)
    if lever_site:
        return {"type": "lever", "status": "confirmed", "detail": f"site={lever_site}"}
    if "data.usajobs.gov" in lower or "usajobs.gov" in lower:
        return {"type": "api", "status": "confirmed", "detail": "USAJobs public API/listing"}
    for signal in UNSUPPORTED_SIGNALS:
        if signal in lower:
            return {"type": "unsupported/login portal", "status": "unsupported", "detail": signal}
    if html:
        return {"type": "manual/public career page", "status": "needs manual review", "detail": "public page fetched; no supported ATS signal found"}
    return {"type": "unknown", "status": "needs manual review", "detail": "network unavailable or no public signal"}


def source_lookup() -> dict[str, dict[str, Any]]:
    saved = {source["name"]: source for source in db.list_sources()}
    rows = {}
    for source in load_sources():
        source = {**source, **saved.get(source["name"], {})}
        name = source["name"].lower()
        for suffix in (" careers", " api", " source"):
            name = name.replace(suffix, "")
        rows[name.strip()] = source
    return rows


def source_for(target: dict[str, str], sources: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = target["organization"].lower()
    return sources.get(key) or sources.get(f"{key} source")


def discover(targets: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    rows = []
    sources = source_lookup()
    for target in targets or read_targets():
        url = target["url"]
        final_url, html, fetch_error = fetch_url(url) if url.startswith("http") else (url, "", "missing public URL")
        classification = classify_url(url, html, final_url)
        confirmed_or_unsupported = classification["type"] in {"api", "greenhouse", "lever", "unsupported/login portal"}
        configured = source_for(target, sources)
        rows.append(
            {
                **target,
                "final_url": final_url,
                "discovered_type": classification["type"],
                "discovery_status": classification["status"] if confirmed_or_unsupported else ("needs manual review" if fetch_error else classification["status"]),
                "detail": classification["detail"] if confirmed_or_unsupported else (fetch_error or classification["detail"]),
                "configured_type": configured.get("type", "") if configured else "",
                "configured_enabled": str(bool(configured.get("enabled"))).lower() if configured else "false",
                "validation_result": configured.get("validation_status") or configured.get("last_status") or "not validated" if configured else "not configured",
            }
        )
    return rows


def write_reports(rows: list[dict[str, str]]) -> None:
    now = datetime.now(UTC).isoformat()
    discovery = [
        "# Source Discovery Report",
        "",
        f"Generated: {now}",
        "",
        "No jobs are inserted by this report. Unsupported/login portals are not automated.",
        "",
        "| Organization | Career URL | Discovered type | Status | Detail | Configured type | Enabled |",
        "|---|---|---|---|---|---|---|",
    ]
    activation = [
        "# Source Activation Status",
        "",
        f"Generated: {now}",
        "",
        "| Organization | Source type | Status | Career URL | Date support | Validation result | Next action |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        detail = redact(row["detail"]).replace("|", "/")
        discovery.append(
            f"| {row['organization']} | {row['url']} | {row['discovered_type']} | {row['discovery_status']} | {detail} | {row['configured_type'] or 'not configured'} | {row['configured_enabled']} |"
        )
        if row["configured_enabled"] == "true":
            status = "active"
            next_action = "Run validate_target_sources.py, then refresh."
        elif row["discovered_type"] in {"greenhouse", "lever", "api"} and row["discovery_status"] == "confirmed":
            status = "disabled"
            next_action = "Add/confirm config, validate, then enable."
        elif row["discovered_type"].startswith("unsupported"):
            status = "unsupported"
            next_action = "Manual browser review only."
        else:
            status = "needs manual review"
            next_action = "Confirm public ATS or keep manual."
        activation.append(
            f"| {row['organization']} | {row['discovered_type']} | {status} | {row['url']} | {row['date_support']} | {row['validation_result']} | {next_action} |"
        )
    DISCOVERY_REPORT_PATH.write_text("\n".join(discovery) + "\n", encoding="utf-8")
    ACTIVATION_STATUS_PATH.write_text("\n".join(activation) + "\n", encoding="utf-8")


def main() -> int:
    rows = discover()
    write_reports(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["discovered_type"]] = counts.get(row["discovered_type"], 0) + 1
    print(f"discovered sources: {len(rows)}")
    for kind, count in sorted(counts.items()):
        print(f"- {kind}: {count}")
    print(f"report: {DISCOVERY_REPORT_PATH}")
    print(f"activation status: {ACTIVATION_STATUS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
