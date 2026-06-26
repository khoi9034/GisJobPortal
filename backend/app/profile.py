from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import PROFILE_PATH


def load_profile(path: Path | str = PROFILE_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        profile = yaml.safe_load(handle) or {}
    required = ["name", "email", "location", "portfolio", "skills", "target_roles"]
    missing = [key for key in required if not profile.get(key)]
    if missing:
        raise ValueError(f"Missing profile fields: {', '.join(missing)}")
    return profile

