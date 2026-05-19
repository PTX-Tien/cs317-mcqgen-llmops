from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

def _version_dirs() -> list[Path]:
    dirs = []
    env_version = os.getenv("PROMPT_VERSION", "").strip()
    if env_version:
        dirs.append(PROMPTS_DIR / env_version)

    current = PROMPTS_DIR / "current"
    if current.exists():
        if current.is_dir() or current.is_symlink():
            dirs.append(current.resolve())
        else:
            try:
                value = current.read_text(encoding="utf-8").strip()
                if value:
                    dirs.append(PROMPTS_DIR / value)
            except OSError:
                pass

    dirs.extend([PROMPTS_DIR / "v2", PROMPTS_DIR / "v1"])
    return dirs

def load_json_asset(filename: str, default: Any | None = None) -> Any:
    for directory in _version_dirs():
        path = directory / filename
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    return {} if default is None else default

def load_opening_families() -> list[dict[str, Any]]:
    data = load_json_asset("opening_families.json", {"families": []})
    if isinstance(data, dict):
        return data.get("families", [])
    return data if isinstance(data, list) else []

def load_weak_openings() -> list[str]:
    data = load_json_asset("bad_openings.json", {"weak_openings": []})
    if isinstance(data, dict):
        return data.get("weak_openings", [])
    return []
