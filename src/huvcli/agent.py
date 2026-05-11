from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provider import ApiClient
from .storage import append_history, ensure_workspace
from .tools import ToolContext, call_tool
from .ui import UI


SYSTEM_PROMPT = """You are Huv, a CLI coding agent.
Work inside the user's current project only.
Use tools by replying with strict JSON only:
{"action":"tool","tool":"list_files","args":{"max_files":200}}
{"action":"tool","tool":"read_file","args":{"path":"README.md"}}
{"action":"tool","tool":"apply_patch","args":{"patch":"--- README.md\n+++ README.md\n@@ -1 +1 @@\n-old\n+new\n"}}
{"action":"tool","tool":"write_file","args":{"path":"file.txt","content":"new contents"}}
{"action":"tool","tool":"run_command","args":{"command":"python -m pytest"}}
{"action":"tool","tool":"run_command","args":{"command":"Remove-Item old.txt","dangerous":true}}
When finished:
{"action":"final","text":"Concrete answer with what you found, what you changed or recommend, and next steps."}
Return exactly one JSON object per reply. Prose outside JSON is ignored.
Prefer apply_patch for edits. Read files before editing. Keep changes small and explain results at end.
Never use placeholder text such as "short summary". Final text must be useful to the user.
"""


def _project_guidance(cwd: Path) -> str:
    path = cwd / "HUV.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n\nProject guidance from HUV.md:\n" + text[:12000]


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise json.JSONDecodeError("Unterminated JSON object", text, start)


def _parse_action(text: str) -> dict[str, Any]:
    action = json.loads(_extract_json_object(text))
    if not isinstance(action, dict):
        raise json.JSONDecodeError("JSON action must be an object", text, 0)
    return action


def _status_for(tool: str) -> str:
    return {
        "list_files": "Checking files...",
        "read_file": "Reading context...",
        "apply_patch": "Editing...",
        "write_file": "Writing...",
        "run_command": "Running check...",
    }.get(tool, "Working...")


def _status_kind(tool: str) -> str:
    return {
        "list_files": "files",
        "read_file": "read",
        "apply_patch": "edit",
        "write_file": "write",
        "run_command": "run",
    }.get(tool, "think")


def _result_summary(tool: str, result: str) -> str:
    first = result.strip().splitlines()[0] if result.strip() else "done"
    if tool == "list_files":
        count = len([line for line in result.splitlines() if line and line != "...truncated"])
        return f"Found {count} files."
    if tool == "read_file":
        return "Read file."
    if tool in {"apply_patch", "write_file"}:
        return first
    if tool == "run_command":
        return first
    return "Done."


def _is_bad_final(answer: str) -> bool:
    normalized = " ".join(answer.strip().lower().split())
    if not normalized:
        return True
    placeholders = {
        "short summary",
        "summary",
        "done",
        "complete",
        "finished",
        "ok",
    }
    if normalized in placeholders:
        return True
    return len(answer.strip()) < 30


def run_agent(
    prompt: str,
    cwd: Path,
    yes: bool = False,
    max_steps: int = 30,
    verbose: bool = False,
    save: bool = True,
    plain: bool = False,
) -> str:
    client = ApiClient()
    ui = UI(plain=plain)
    ctx = ToolContext(cwd=cwd, yes=yes, verbose=verbose)
    prefs = ensure_workspace(cwd)
    if not save:
        prefs["save_history"] = False
    tool_log: list[dict[str, str]] = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + _project_guidance(cwd)},
        {"role": "user", "content": prompt},
    ]
    for _ in range(max_steps):
        reply = client.complete(messages)
        messages.append({"role": "assistant", "content": reply})
        try:
            action = _parse_action(reply)
        except json.JSONDecodeError:
            messages.append(
                {
                    "role": "user",
                    "content": "Reply with exactly one JSON object using the documented action schema.",
                }
            )
            continue
        if action.get("action") == "final":
            answer = str(action.get("text", ""))
            if _is_bad_final(answer):
                print(ui.status("Planning summary...", "think"))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That final answer was too short or placeholder text. "
                            "Reply with a real, helpful final JSON object. Include concrete findings, "
                            "what you checked, and recommended next steps."
                        ),
                    }
                )
                continue
            append_history(cwd, prompt, answer, tool_log, prefs)
            return answer
        if action.get("action") != "tool":
            answer = f"Unknown action: {reply}"
            append_history(cwd, prompt, answer, tool_log, prefs)
            return answer
        tool_name = str(action["tool"])
        print(ui.status(_status_for(tool_name), _status_kind(tool_name)))
        try:
            result = call_tool(ctx, tool_name, dict(action.get("args") or {}))
        except Exception as exc:
            result = f"Tool error: {exc}"
        if verbose:
            print(f"\n[{tool_name}]\n{result[:4000]}\n")
        else:
            summary = _result_summary(tool_name, result)
            print(ui.result(summary, ok=not summary.lower().startswith(("tool error", "command blocked"))))
        tool_log.append({"tool": tool_name, "summary": _result_summary(tool_name, result)})
        messages.append({"role": "user", "content": f"Tool result:\n{result}"})
    answer = "Stopped: max steps reached"
    append_history(cwd, prompt, answer, tool_log, prefs)
    return answer
