"""User-defined hooks (CC-style).

Config: `.huvcli/hooks.json` at project root, optional. Shape:

    {
      "pre_tool":  [{"matcher": "edit_file|write_file", "command": "..."}],
      "post_tool": [{"matcher": "run_command",         "command": "..."}],
      "user_prompt":[{"command": "..."}],
      "stop":       [{"command": "..."}]
    }

Each hook is a shell command. We invoke it with the event payload on stdin
as a single-line JSON object. The hook may:
  * exit 0 → allow (stdout appended to tool result for context)
  * exit non-zero → block tool call; stdout/stderr returned to the model
  * print a JSON object with {"decision": "block"|"allow", "reason": "..."}
    on stdout to be explicit (overrides exit code for `decision`)

`matcher` is a regex against the tool name; omit to match all tools.
Hooks never run for `mcp__*` tools (those are external by definition).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


HOOKS_FILENAME = "hooks.json"
HOOK_EVENTS = {"pre_tool", "post_tool", "user_prompt", "stop"}


def hooks_path(cwd: Path) -> Path:
    return cwd / ".huvcli" / HOOKS_FILENAME


def load_hooks(cwd: Path) -> dict[str, list[dict[str, str]]]:
    path = hooks_path(cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, list[dict[str, str]]] = {}
    for event, entries in data.items():
        if event not in HOOK_EVENTS or not isinstance(entries, list):
            continue
        items: list[dict[str, str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cmd = str(entry.get("command", "")).strip()
            if not cmd:
                continue
            items.append({
                "matcher": str(entry.get("matcher", "")).strip(),
                "command": cmd,
            })
        if items:
            cleaned[event] = items
    return cleaned


def _matches(matcher: str, tool: str | None) -> bool:
    if not matcher:
        return True
    if tool is None:
        return False
    try:
        return re.search(matcher, tool) is not None
    except re.error:
        return matcher == tool


def run_hooks(
    cwd: Path,
    hooks: dict[str, list[dict[str, str]]],
    event: str,
    payload: dict[str, Any],
    timeout: int = 20,
) -> tuple[bool, str]:
    """Run all matching hooks for `event`. Returns (allowed, combined_output)."""
    entries = hooks.get(event, [])
    if not entries:
        return True, ""
    tool = payload.get("tool")
    if isinstance(tool, str) and tool.startswith("mcp__"):
        return True, ""
    combined: list[str] = []
    allowed = True
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for entry in entries:
        if not _matches(entry["matcher"], tool):
            continue
        try:
            result = subprocess.run(
                entry["command"],
                cwd=cwd, shell=True, input=body,
                capture_output=True, timeout=max(1, min(timeout, 120)),
            )
        except subprocess.TimeoutExpired:
            allowed = False
            combined.append(f"hook timeout: {entry['command']}")
            continue
        out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        decision: str | None = None
        reason: str | None = None
        if out.startswith("{"):
            try:
                obj = json.loads(out.splitlines()[0])
                if isinstance(obj, dict):
                    decision = str(obj.get("decision", "")).lower() or None
                    reason = obj.get("reason")
            except json.JSONDecodeError:
                pass
        if result.returncode != 0 or decision == "block":
            allowed = False
            combined.append(
                f"hook blocked ({entry['command']}): {reason or err or out or f'exit={result.returncode}'}"
            )
            break
        if out and decision != "allow":
            combined.append(f"hook ({entry['command']}): {out}")
    return allowed, "\n".join(combined)
