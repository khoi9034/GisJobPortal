from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import SEARCH_PROFILES_PATH, SOURCES_PATH

SOURCE_TYPES = {"api", "rss", "greenhouse", "lever", "static_url", "manual"}


def load_sources(path: Path | str = SOURCES_PATH) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    sources = data.get("sources", [])
    for source in sources:
        if source.get("type") not in SOURCE_TYPES:
            raise ValueError(f"Unsupported source type: {source.get('type')}")
    return sources


def load_search_profiles(path: Path | str = SEARCH_PROFILES_PATH) -> dict[str, dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("profiles", {})


def save_source(source: dict[str, Any], path: Path | str = SOURCES_PATH) -> dict[str, Any]:
    if source.get("type") not in SOURCE_TYPES:
        raise ValueError(f"Unsupported source type: {source.get('type')}")
    sources = load_sources(path)
    names = [item["name"] for item in sources]
    if source["name"] in names:
        sources[names.index(source["name"])] = source
    else:
        sources.append(source)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump({"sources": sources}, handle, sort_keys=False)
    return source
