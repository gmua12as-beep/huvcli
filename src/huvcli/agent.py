from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compact import compact_if_needed, needs_compaction
from .hooks import load_hooks, run_hooks
from .mcp import MCPRegistry
from .provider import ApiClient
from .storage import append_history, ensure_workspace, load_conversation, save_conversation
from .tools import TOOL_SCHEMAS, ToolContext, call_tool
from .ui import UI


SYSTEM_PROMPT = """You are Huv, a CLI coding agent working in the user's project directory only.

Tool guidelines:
- ALWAYS read_file before edit_file or apply_patch — the edit tools refuse stale edits.
- Prefer edit_file (exact-string replace) for changes. It refuses ambiguous matches, so include enough surrounding context in old_string to make it unique. This prevents wrong-line edits.
- Use grep/glob to locate code instead of reading whole files. Use read_file with offset/limit on large files.
- Use update_plan at the start of any multi-step task; mark steps in_progress/completed as you go.
- Use apply_patch for multi-file edits or when adding/deleting files. Accepts unified diff or `*** Begin Patch ... *** End Patch` envelope.
- run_command for tests/builds. Set dangerous=true only when intentional.
- Keep changes minimal. After editing, run the relevant tests/build to verify.
- Final answer must be concrete: what you found, what you changed, how to verify. No placeholder text.
- Do NOT emit `<think>` blocks or `<tool_call>` / `<minimax:tool_call>` XML in your reply. Use the provided function-calling interface for tool invocations. If you must reason, keep it brief and inline — never inside tags.
"""


def _project_guidance(cwd: Path) -> str:
    parts: list[str] = []
    for name in ("HUV.md", "AGENTS.md", "CLAUDE.md"):
        path = cwd / name
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"--- {name} ---\n{text[:12000]}")
    if not parts:
        return ""
    return "\n\nProject guidance:\n" + "\n\n".join(parts)


import re as _re

_THINK_RE = _re.compile(r"<think\b[^>]*>.*?</think>", _re.IGNORECASE | _re.DOTALL)
_TOOL_BLOCK_RE = _re.compile(
    r"<(?:[a-z]+:)?tool_call\b[^>]*>(.*?)</(?:[a-z]+:)?tool_call>",
    _re.IGNORECASE | _re.DOTALL,
)
_INVOKE_RE = _re.compile(
    r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>',
    _re.IGNORECASE | _re.DOTALL,
)
_PARAM_RE = _re.compile(
    r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>',
    _re.IGNORECASE | _re.DOTALL,
)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _coerce_param(value: str) -> Any:
    """Heuristically convert XML parameter text into a Python value."""
    v = value.strip()
    if v in {"true", "True"}:
        return True
    if v in {"false", "False"}:
        return False
    if v.lstrip("-").isdigit():
        try:
            return int(v)
        except ValueError:
            return value
    # Keep verbatim string (preserves whitespace inside content blocks).
    return value


def _parse_xml_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse MiniMax-style `<minimax:tool_call><invoke name="..."><parameter ...>` blocks.

    Returns the same shape as native tool_calls: [{id, name, args}].
    """
    calls: list[dict[str, Any]] = []
    counter = 0
    for block in _TOOL_BLOCK_RE.findall(text):
        for name, inner in _INVOKE_RE.findall(block):
            args: dict[str, Any] = {}
            for pname, pvalue in _PARAM_RE.findall(inner):
                args[pname] = _coerce_param(pvalue)
            counter += 1
            calls.append({"id": f"xml_{counter}", "name": name.strip(), "args": args})
    return calls


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


_STATUS = {
    "list_files": ("Checking files...", "files"),
    "glob": ("Globbing...", "files"),
    "grep": ("Searching...", "files"),
    "read_file": ("Reading...", "read"),
    "apply_patch": ("Patching...", "edit"),
    "edit_file": ("Editing...", "edit"),
    "write_file": ("Writing...", "write"),
    "run_command": ("Running...", "run"),
    "update_plan": ("Planning...", "think"),
}


def _result_summary(tool: str, result: str) -> str:
    first = result.strip().splitlines()[0] if result.strip() else "done"
    if tool == "list_files":
        count = len([line for line in result.splitlines() if line and line != "...truncated"])
        return f"Found {count} files."
    if tool == "glob":
        return f"Glob: {first}"
    if tool == "grep":
        count = len(result.splitlines())
        return f"{count} match(es)" if result != "(no matches)" else "No matches"
    if tool == "read_file":
        return first
    if tool in {"apply_patch", "write_file", "edit_file"}:
        return first
    if tool == "run_command":
        return first
    if tool == "update_plan":
        return "Plan updated."
    return "Done."


def _is_bad_final(answer: str) -> bool:
    normalized = " ".join(answer.strip().lower().split())
    if not normalized:
        return True
    placeholders = {"short summary", "summary", "done", "complete", "finished", "ok"}
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
    approval: str = "suggest",
    resume: bool = False,
) -> str:
    client = ApiClient()
    ui = UI(plain=plain)
    ctx = ToolContext(cwd=cwd, yes=yes, verbose=verbose, approval=approval)
    prefs = ensure_workspace(cwd)
    if not save:
        prefs["save_history"] = False
    tool_log: list[dict[str, str]] = []

    hooks = load_hooks(cwd)
    mcp = MCPRegistry(cwd)
    mcp_schemas = mcp.discover() if mcp.config else []
    if mcp_schemas:
        print(ui.dim(f"MCP: {len(mcp_schemas)} tool(s) from {len(mcp.config)} server(s)"))

    # user_prompt hook (can block before sending to model)
    if hooks:
        allowed, output = run_hooks(cwd, hooks, "user_prompt", {"prompt": prompt})
        if not allowed:
            return f"Blocked by user_prompt hook:\n{output}"

    system = {"role": "system", "content": SYSTEM_PROMPT + _project_guidance(cwd)}
    messages: list[dict[str, Any]] = [system]
    if resume:
        prior = load_conversation(cwd)
        if prior:
            messages.extend(prior)
    messages.append({"role": "user", "content": prompt})

    use_native_tools = client.config.use_tools
    all_schemas = TOOL_SCHEMAS + mcp_schemas

    def _dispatch(name: str, args: dict[str, Any]) -> str:
        if mcp.has(name):
            return mcp.call(name, args)
        return call_tool(ctx, name, args)

    def _run_tool(name: str, args: dict[str, Any]) -> str:
        if hooks:
            allowed, hook_out = run_hooks(cwd, hooks, "pre_tool", {"tool": name, "args": args})
            if not allowed:
                return f"Tool blocked by hook: {hook_out}"
            prefix = (hook_out + "\n") if hook_out else ""
        else:
            prefix = ""
        try:
            result = _dispatch(name, args)
        except Exception as exc:  # noqa: BLE001
            result = f"Tool error: {exc}"
        if hooks:
            _, post_out = run_hooks(
                cwd, hooks, "post_tool",
                {"tool": name, "args": args, "result": result[:8000]},
            )
            if post_out:
                result = result + "\n" + post_out
        return prefix + result

    def _finalize(answer: str) -> str:
        answer = _strip_think(answer)
        if ctx.changes:
            print(ui.changed_files(ctx.changes))
        append_history(cwd, prompt, answer, tool_log, prefs)
        if save:
            save_conversation(cwd, messages)
        if hooks:
            run_hooks(
                cwd, hooks, "stop",
                {"prompt": prompt, "answer": answer, "tools": tool_log, "changes": ctx.changes},
            )
        mcp.close_all()
        return answer

    for _ in range(max_steps):
        if needs_compaction(messages):
            print(ui.status("Compacting context...", "think"))
            messages, did = compact_if_needed(messages, client.summarize)
            if did and verbose:
                print(ui.dim("[compacted older turns into summary]"))
        reply = client.complete(messages, tools=all_schemas if use_native_tools else None)
        text = reply.get("text", "")
        tool_calls = reply.get("tool_calls") or []

        # Fallback: some models (MiniMax) emit tool calls as XML inside text
        # instead of using native function-calling. Parse + execute them
        # without trying to round-trip through the API's tool_calls schema
        # (the provider didn't produce structured calls, so we shouldn't
        # fabricate them in the message history).
        xml_calls: list[dict[str, Any]] = []
        if not tool_calls and text and "<" in text:
            xml_calls = _parse_xml_tool_calls(text)

        if xml_calls:
            # Record the assistant turn as plain text (XML + think stripped).
            cleaned = _strip_think(_TOOL_BLOCK_RE.sub("", text))
            messages.append({"role": "assistant", "content": cleaned or None})
            for tc in xml_calls:
                name = tc["name"]
                label, kind = _STATUS.get(name, ("Working...", "think"))
                print(ui.status(label, kind))
                result = _run_tool(name, dict(tc["args"] or {}))
                summary = _result_summary(name, result)
                ok = not summary.lower().startswith(("tool error", "command blocked"))
                if verbose:
                    print(ui.tool_call(name, summary, ok=ok))
                    print(ui.dim(result[:4000]))
                elif name == "update_plan" and ctx.plan:
                    print(ui.tool_call(name, "plan updated", ok=ok))
                    print(ui.plan(ctx.plan))
                else:
                    print(ui.tool_call(name, summary, ok=ok))
                tool_log.append({"tool": name, "summary": summary})
                messages.append({"role": "user", "content": f"Tool result ({name}):\n{result[:24000]}"})
            continue

        if tool_calls:
            # Native function-calling path.
            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                name = tc["name"]
                label, kind = _STATUS.get(name, ("Working...", "think"))
                print(ui.status(label, kind))
                result = _run_tool(name, dict(tc["args"] or {}))
                summary = _result_summary(name, result)
                ok = not summary.lower().startswith(("tool error", "command blocked"))
                if verbose:
                    print(ui.tool_call(name, summary, ok=ok))
                    print(ui.dim(result[:4000]))
                elif name == "update_plan" and ctx.plan:
                    print(ui.tool_call(name, "plan updated", ok=ok))
                    print(ui.plan(ctx.plan))
                else:
                    print(ui.tool_call(name, summary, ok=ok))
                tool_log.append({"tool": name, "summary": summary})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result[:24000],
                })
            continue

        # JSON-in-prose fallback path.
        messages.append({"role": "assistant", "content": text})
        try:
            action = _parse_action(text)
        except json.JSONDecodeError:
            # If we got no tool calls and no JSON, treat as final.
            answer = text.strip()
            if _is_bad_final(answer):
                messages.append({
                    "role": "user",
                    "content": "Reply with a tool call or a final JSON object {\"action\":\"final\",\"text\":\"...\"}.",
                })
                continue
            return _finalize(answer)
        if action.get("action") == "final":
            answer = str(action.get("text", ""))
            if _is_bad_final(answer):
                messages.append({
                    "role": "user",
                    "content": "Final too short. Reply with concrete findings, changes, next steps.",
                })
                continue
            return _finalize(answer)
        if action.get("action") != "tool":
            return _finalize(f"Unknown action: {text}")
        name = str(action["tool"])
        label, kind = _STATUS.get(name, ("Working...", "think"))
        print(ui.status(label, kind))
        result = _run_tool(name, dict(action.get("args") or {}))
        summary = _result_summary(name, result)
        ok = not summary.lower().startswith(("tool error", "command blocked"))
        if verbose:
            print(ui.tool_call(name, summary, ok=ok))
            print(ui.dim(result[:4000]))
        elif name == "update_plan" and ctx.plan:
            print(ui.tool_call(name, "plan updated", ok=ok))
            print(ui.plan(ctx.plan))
        else:
            print(ui.tool_call(name, summary, ok=ok))
        tool_log.append({"tool": name, "summary": summary})
        messages.append({"role": "user", "content": f"Tool result:\n{result[:24000]}"})

    return _finalize("Stopped: max steps reached")
