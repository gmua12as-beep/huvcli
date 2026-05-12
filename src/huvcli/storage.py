from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PREFS: dict[str, Any] = {
    "save_history": True,
    "max_prompt_chars": 4000,
    "max_answer_chars": 8000,
    "max_history_rows": 200,
}


def workspace_dir(cwd: Path) -> Path:
    return cwd / ".huvcli"


def prefs_path(cwd: Path) -> Path:
    return workspace_dir(cwd) / "prefs.json"


def history_path(cwd: Path) -> Path:
    return workspace_dir(cwd) / "conversations.jsonl"


def conversation_path(cwd: Path) -> Path:
    return workspace_dir(cwd) / "last_conversation.json"


def save_conversation(cwd: Path, messages: list[dict[str, Any]]) -> None:
    # Drop system message — agent re-prepends fresh one on resume.
    payload = [m for m in messages if m.get("role") != "system"]
    path = conversation_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_conversation(cwd: Path) -> list[dict[str, Any]]:
    path = conversation_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def load_prefs(cwd: Path) -> dict[str, Any]:
    path = prefs_path(cwd)
    if not path.exists():
        return dict(DEFAULT_PREFS)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PREFS)
    if not isinstance(loaded, dict):
        return dict(DEFAULT_PREFS)
    prefs = dict(DEFAULT_PREFS)
    prefs.update(loaded)
    return prefs


def save_prefs(cwd: Path, prefs: dict[str, Any]) -> None:
    path = prefs_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_workspace(cwd: Path) -> dict[str, Any]:
    prefs = load_prefs(cwd)
    save_prefs(cwd, prefs)
    return prefs


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...truncated"


def append_history(
    cwd: Path,
    prompt: str,
    answer: str,
    tools: list[dict[str, str]],
    prefs: dict[str, Any] | None = None,
) -> None:
    prefs = prefs or load_prefs(cwd)
    if not prefs.get("save_history", True):
        return
    path = history_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": _truncate(prompt, int(prefs.get("max_prompt_chars", 4000))),
        "answer": _truncate(answer, int(prefs.get("max_answer_chars", 8000))),
        "tools": tools,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def recent_history(cwd: Path, limit: int = 10) -> list[dict[str, Any]]:
    path = history_path(cwd)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows[-limit:]


def set_pref(cwd: Path, key: str, value: str) -> dict[str, Any]:
    prefs = ensure_workspace(cwd)
    parsed: Any = value
    lowered = value.lower()
    if lowered in {"true", "false"}:
        parsed = lowered == "true"
    else:
        try:
            parsed = int(value)
        except ValueError:
            parsed = value
    prefs[key] = parsed
    save_prefs(cwd, prefs)
    return prefs
