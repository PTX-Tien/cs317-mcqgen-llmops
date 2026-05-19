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

# ── Phase 2: Style Bank + Few-shot ──────────────────────────

def load_style_bank() -> list[dict[str, Any]]:
    data = load_json_asset("style_bank.json", {"examples": []})
    if isinstance(data, dict):
        return data.get("examples", [])
    return data if isinstance(data, list) else []

def load_bad_opening_examples() -> list[dict[str, Any]]:
    data = load_json_asset("bad_openings.json", {"examples": []})
    if isinstance(data, dict):
        return data.get("examples", [])
    return []

def select_fewshot_examples(
    topic: str,
    opening_family: str,
    difficulty: str = "G2",
    n: int = 2,
) -> list[dict[str, Any]]:
    """Chọn n ví dụ few-shot: ưu tiên 1 cùng opening_family + 1 khác family."""
    bank = load_style_bank()
    if not bank:
        return []

    topic_lower = topic.lower()
    same_family = [e for e in bank if e.get("opening_family") == opening_family]
    diff_family = [e for e in bank if e.get("opening_family") != opening_family]

    result: list[dict[str, Any]] = []

    # Pick 1 from same family (prefer same topic)
    if same_family:
        same_topic = [e for e in same_family if topic_lower in " ".join(e.get("topic_tags", [])).lower()]
        result.append(same_topic[0] if same_topic else same_family[0])

    # Pick 1 from different family (prefer same topic)
    if diff_family:
        same_topic = [e for e in diff_family if topic_lower in " ".join(e.get("topic_tags", [])).lower()]
        pick = same_topic[0] if same_topic else diff_family[0]
        if pick not in result:
            result.append(pick)

    # Fill if needed
    for e in bank:
        if len(result) >= n:
            break
        if e not in result:
            result.append(e)

    return result[:n]
