from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.paths import SOURCES_PATH  # noqa: E402


def read_config(path: Path = SOURCES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"sources": []}


def write_config(data: dict, path: Path = SOURCES_PATH) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def set_enabled(name: str, enabled: bool, path: Path = SOURCES_PATH) -> dict:
    data = read_config(path)
    found = None
    for source in data.get("sources", []):
        if source.get("name") == name:
            source["enabled"] = enabled
            found = source
            break
    if not found:
        raise ValueError(f"Source not found: {name}")

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    in_source = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- name: "):
            in_source = stripped == f"- name: {name}"
        elif in_source and stripped.startswith("enabled:"):
            lines[index] = f"{line[:len(line) - len(line.lstrip())]}enabled: {str(enabled).lower()}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return found
    write_config(data, path)
    return found


def list_sources(path: Path = SOURCES_PATH) -> list[dict]:
    return read_config(path).get("sources", [])


def main(argv: list[str] | None = None, path: Path = SOURCES_PATH) -> int:
    args = argv or sys.argv[1:]
    if not args or args[0] not in {"list", "enable", "disable"}:
        print('Usage: python scripts/source_toggle.py list|enable|disable "Source Name"')
        return 2
    try:
        if args[0] == "list":
            for source in list_sources(path):
                print(f"{source.get('name')} [{source.get('type')}] - {'enabled' if source.get('enabled') else 'disabled'}")
            return 0
        if len(args) < 2:
            print("Source name required.")
            return 2
        source = set_enabled(args[1], args[0] == "enable", path)
        print(f"{source['name']} {'enabled' if source['enabled'] else 'disabled'}.")
        return 0
    except ValueError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
